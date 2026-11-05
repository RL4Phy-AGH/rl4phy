"""Analysis of the SiPlate simulation: energy loss and multiple scattering.

Run from the directory holding the simulation output (e.g. build/):

    python ../analysis/analyze_siplate.py                    # run tag "siplate"
    python ../analysis/analyze_siplate.py --tag test --n-reference 1000

The run is split by event ID into two samples (see siplate_io.py):
    reference   the first n_reference events: smooth reference distributions
    simulation  the remaining events: the target, event-by-event sample
n_reference defaults to /siplate/output/referenceEvents of the run.

Per sample, written to <out>/<tag>/<sample>/:
    energy_loss.png           primary energy loss against Landau theory (Bichsel
                              most probable value, width xi) and fits (Landau,
                              Landau convolved with a Gaussian); energy loss
                              compared with the energy deposited in the plate
    scattering_projected.png  projected angle against Moliere and Highland
    scattering_space.png      space angle against Moliere and Highland
    scattering_2d.png         (theta_x, theta_y) map
    depth_profile.png         dE/dx and angular width vs depth   (needs steps)
    step_distributions.png    per-step energy loss, angle, length (needs steps)
    histograms.npz            binned distributions on the reference binning
                              (for the reference sample: the reference templates)
    summary.json              theory parameters, fit results, statistics

The simulation sample is also compared with the reference on the reference
binning: compare_*.png plus chi2 and Kolmogorov-Smirnov tests in its
summary.json.

Energy-loss and scattering comparisons use "clean" events: the primary left the
plate without a hadronic interaction, which neither theory describes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from loguru import logger  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402
from scipy import optimize, stats  # noqa: E402

import theory  # noqa: E402
from siplate_io import Sample, load_run  # noqa: E402

N_BINS = 200
FIT_LEFT_FRACTION = 0.01  # Landau fit window: down to 1% of the peak on the left
FIT_RIGHT_FRACTION = 0.05  # and to 5% of the peak on the right

C_DATA = "#2a78d6"
C_THEORY = "#eb6834"
C_FIT = "#1baf7a"
C_FIT2 = "#eda100"
C_MUTED = "#8a8a85"

plt.rcParams.update(
    {
        "axes.grid": True,
        "grid.color": "#e4e3df",
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "font.size": 10,
    }
)


# --------------------------------------------------------------------------- #
# Binning and histogram helpers
# --------------------------------------------------------------------------- #


def scattering_beam(sample: Sample) -> theory.Beam:
    """Beam at mid-depth, where scattering theory is evaluated."""
    mean_loss = sample.clean["primary_eloss"].mean()
    return sample.beam.at(sample.beam.ekin - mean_loss / 2)


def make_edges(sample: Sample) -> dict[str, np.ndarray]:
    """Bin edges derived from a sample (the reference: shared by both samples).
    Energies in keV, angles in mrad."""
    c = sample.clean
    theta0 = (
        theory.highland_theta0(
            scattering_beam(sample), sample.material, sample.thickness_mm
        )
        * 1e3
    )

    def energy_edges(values_kev):
        lo, hi = np.quantile(values_kev, [0.0002, 0.995])
        return np.linspace(lo, hi, N_BINS + 1)

    return {
        "eloss_keV": energy_edges(c["primary_eloss"] * 1e3),
        "edep_keV": energy_edges(c["edep_total"] * 1e3),
        "theta_projected_mrad": np.linspace(-10 * theta0, 10 * theta0, N_BINS + 1),
        "theta_space_mrad": np.linspace(0, 10 * theta0, N_BINS + 1),
    }


def sample_values(sample: Sample) -> dict[str, np.ndarray]:
    c = sample.clean
    return {
        "eloss_keV": c["primary_eloss"].to_numpy() * 1e3,
        "edep_keV": c["edep_total"].to_numpy() * 1e3,
        "theta_projected_mrad": sample.theta_projected,
        "theta_space_mrad": c["primary_theta"].to_numpy(),
    }


def density(values, edges):
    """Histogram normalised to the full sample: (centres, density, error)."""
    counts, _ = np.histogram(values, bins=edges)
    width = np.diff(edges)
    norm = len(values) * width
    return 0.5 * (edges[1:] + edges[:-1]), counts / norm, np.sqrt(counts) / norm


def half_max_width(x, y):
    """Peak position and FWHM of a sampled curve, linear interpolation."""
    i = int(np.argmax(y))
    half = y[i] / 2
    left = np.where(y[:i] < half)[0]
    right = np.where(y[i:] < half)[0]
    if not len(left) or not len(right):
        return float(x[i]), float("nan")
    j, k = left[-1], i + right[0]
    xl = np.interp(half, [y[j], y[j + 1]], [x[j], x[j + 1]])
    xr = np.interp(half, [y[k], y[k - 1]], [x[k], x[k - 1]])
    return float(x[i]), float(xr - xl)


def smooth(y, n=5):
    return np.convolve(y, np.ones(n) / n, mode="same")


def ratio_panel(ax, x, num, num_err, den, label):
    good = den > 0
    r = np.full_like(num, np.nan)
    r_err = np.full_like(num, np.nan)
    r[good] = num[good] / den[good]
    r_err[good] = num_err[good] / den[good]
    ax.errorbar(x, r, yerr=r_err, fmt="o", ms=2.5, color=C_DATA, elinewidth=0.8)
    ax.axhline(1, color=C_MUTED, lw=1)
    ax.set_ylim(0.5, 1.5)
    ax.set_ylabel(label)


# --------------------------------------------------------------------------- #
# Energy loss
# --------------------------------------------------------------------------- #


def fit_energy_loss(eloss_kev: np.ndarray) -> dict:
    """Landau and Landau (x) Gauss fits to the core of the energy-loss histogram."""
    lo, hi = np.quantile(eloss_kev, [0.0002, 0.99])
    edges = np.linspace(lo, hi, 2 * N_BINS + 1)
    counts, _ = np.histogram(eloss_kev, bins=edges)
    x = 0.5 * (edges[1:] + edges[:-1])
    width = edges[1] - edges[0]

    peak = int(np.argmax(smooth(counts)))
    sm = smooth(counts)
    left = np.where(sm[:peak] < FIT_LEFT_FRACTION * sm[peak])[0]
    right = np.where(sm[peak:] < FIT_RIGHT_FRACTION * sm[peak])[0]
    i0 = left[-1] if len(left) else 0
    i1 = peak + right[0] if len(right) else len(x) - 1
    xs, ys = x[i0 : i1 + 1], counts[i0 : i1 + 1]
    sig = np.sqrt(np.maximum(ys, 1))

    def landau_model(xv, norm, mpv, xi):
        return norm * width * theory.landau_pdf(xv, mpv, xi)

    def langaus_model(xv, norm, mpv, xi, sigma):
        return norm * width * theory.langaus_pdf(xv, mpv, xi, sigma)

    p0 = [len(eloss_kev), x[peak], (xs[-1] - xs[0]) / 10]
    p_l, cov_l = optimize.curve_fit(landau_model, xs, ys, p0=p0, sigma=sig)
    p_g, cov_g = optimize.curve_fit(
        langaus_model, xs, ys, p0=[*p_l, 0.5 * p_l[2]], sigma=sig, maxfev=20000
    )

    fine = np.linspace(lo, hi, 4000)
    result = {"fit_range_keV": [float(xs[0]), float(xs[-1])]}
    for name, model, p, cov in (
        ("landau", landau_model, p_l, cov_l),
        ("langaus", langaus_model, p_g, cov_g),
    ):
        chi2 = float(np.sum(((ys - model(xs, *p)) / sig) ** 2))
        mode, fwhm = half_max_width(fine, model(fine, *p))
        result[name] = {
            "params": [float(v) for v in p],
            "errors": [float(v) for v in np.sqrt(np.diag(cov))],
            "chi2_ndf": chi2 / (len(xs) - len(p)),
            "mpv_keV": mode,
            "fwhm_keV": fwhm,
        }
    result["langaus"]["sigma_keV"] = abs(float(p_g[3]))
    result["landau"]["xi_keV"] = float(p_l[2])
    result["langaus"]["xi_keV"] = float(p_g[2])
    return result


def analyze_energy_loss(sample: Sample, edges, out: Path) -> dict:
    beam, mat, t = sample.beam, sample.material, sample.thickness_mm
    th = {
        "xi_keV": theory.landau_xi(beam, mat, t) * 1e3,
        "mpv_keV": theory.landau_mpv(beam, mat, t) * 1e3,
        "mean_bethe_keV": theory.bethe_mean_loss(beam, mat, t) * 1e3,
        "t_max_keV": theory.t_max(beam) * 1e3,
        "kappa": theory.landau_kappa(beam, mat, t),
    }
    th["fwhm_keV"] = theory.landau_fwhm_in_xi() * th["xi_keV"]

    eloss = sample.clean["primary_eloss"].to_numpy() * 1e3
    edep = sample.clean["edep_total"].to_numpy() * 1e3
    fits = fit_energy_loss(eloss)

    e = edges["eloss_keV"]
    x, y, yerr = density(eloss, e)
    data_mpv, data_fwhm = half_max_width(x, smooth(y))
    data = {
        "n_clean": len(eloss),
        "mean_keV": float(eloss.mean()),
        "median_keV": float(np.median(eloss)),
        "mpv_keV": data_mpv,
        "fwhm_keV": data_fwhm,
        "edep_mean_keV": float(edep.mean()),
        "escape_mean_keV": float(sample.clean["escape_secondary"].mean() * 1e3),
    }

    fig, (ax, ax_log) = plt.subplots(1, 2, figsize=(13, 5))
    fine = np.linspace(e[0], e[-1], 1000)
    ax.errorbar(
        x,
        y,
        yerr=yerr,
        fmt="o",
        ms=2.5,
        color=C_DATA,
        elinewidth=0.8,
        label=f"Geant4 ({len(eloss):,} events)",
    )
    ax.plot(
        fine,
        theory.landau_pdf(fine, th["mpv_keV"], th["xi_keV"]),
        color=C_THEORY,
        lw=2,
        ls="--",
        label="Landau theory (Bichsel MPV, ξ)",
    )
    pl = fits["landau"]["params"]
    ax.plot(
        fine,
        theory.landau_pdf(fine, pl[1], pl[2]) * pl[0] / len(eloss),
        color=C_FIT,
        lw=2,
        label="Landau fit",
    )
    pg = fits["langaus"]["params"]
    ax.plot(
        fine,
        theory.langaus_pdf(fine, pg[1], pg[2], pg[3]) * pg[0] / len(eloss),
        color=C_FIT2,
        lw=2,
        label="Landau ⊗ Gauss fit",
    )
    ax.axvspan(*fits["fit_range_keV"], color=C_MUTED, alpha=0.08, lw=0)
    ax.set_xlabel("primary energy loss ΔE [keV]")
    ax.set_ylabel("probability density [1/keV]")
    ax.set_title("Energy loss of the primary")
    ax.legend(loc="upper right")
    ax.text(
        0.98,
        0.55,
        "\n".join(
            [
                f"MPV  data {data_mpv:.1f} | theory {th['mpv_keV']:.1f} keV",
                f"FWHM data {data_fwhm:.1f} | theory {th['fwhm_keV']:.1f} keV",
                f"mean data {data['mean_keV']:.1f} | "
                f"Bethe {th['mean_bethe_keV']:.1f} keV",
                f"ξ = {th['xi_keV']:.2f} keV, κ = ξ/T$_{{max}}$ = {th['kappa']:.3f}",
                f"Landau⊗Gauss: σ = {fits['langaus']['sigma_keV']:.1f} keV, "
                f"χ²/ndf = {fits['langaus']['chi2_ndf']:.2f}",
            ]
        ),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.5,
        family="monospace",
    )

    hi = np.quantile(eloss, 0.9999)
    log_edges = np.linspace(0, hi, 300)
    for values, color, label in (
        (eloss, C_DATA, "primary energy loss ΔE"),
        (edep, C_THEORY, "energy deposited in the plate"),
    ):
        xc, yc, _ = density(values, log_edges)
        ax_log.step(xc, yc, where="mid", color=color, lw=1.5, label=label)
    ax_log.set_yscale("log")
    ax_log.set_xlabel("energy [keV]")
    ax_log.set_ylabel("probability density [1/keV]")
    ax_log.set_title(
        f"Tail; mean escaping with secondaries {data['escape_mean_keV']:.2f} keV"
    )
    ax_log.legend()
    fig.tight_layout()
    fig.savefig(out / "energy_loss.png", dpi=150)
    plt.close(fig)

    return {"theory": th, "fits": fits, "data": data}


# --------------------------------------------------------------------------- #
# Multiple scattering
# --------------------------------------------------------------------------- #


def analyze_scattering(sample: Sample, edges, out: Path) -> dict:
    beam = scattering_beam(sample)
    mat, t = sample.material, sample.thickness_mm
    mol = theory.moliere(beam, mat, t)
    theta0 = theory.highland_theta0(beam, mat, t) * 1e3
    proj = sample.theta_projected
    proj_all = np.concatenate(
        [sample.exited["primary_theta_x"], sample.exited["primary_theta_y"]]
    )
    space = sample.clean["primary_theta"].to_numpy()

    def core_sigma(v):
        lo, hi = np.quantile(v, [0.01, 0.99])
        return float(v[(v >= lo) & (v <= hi)].std())

    # Gaussian fit to the central part (|theta| < 2 sigma) of the projected angle.
    x, y, yerr = density(proj, edges["theta_projected_mrad"])
    s98 = core_sigma(proj)
    core = (np.abs(x) < 2 * s98) & (y > 0)
    (amp, sig), _ = optimize.curve_fit(
        lambda xv, a, s: a * np.exp(-0.5 * (xv / s) ** 2),
        x[core],
        y[core],
        p0=[y.max(), s98],
        sigma=yerr[core],
    )
    tail = np.abs(proj) > 3 * mol.sigma_projected * 1e3
    result = {
        "beam_ekin_mid_MeV": beam.ekin,
        "theory": {
            "highland_theta0_mrad": theta0,
            "moliere_chi_c_mrad": mol.chi_c * 1e3,
            "moliere_chi_a_mrad": mol.chi_a * 1e3,
            "moliere_B": mol.B,
            "moliere_theta_m_mrad": mol.theta_m * 1e3,
            "moliere_sigma_projected_mrad": mol.sigma_projected * 1e3,
        },
        "data": {
            "n_clean": len(space),
            "sigma98_projected_mrad": s98,
            "gauss_core_sigma_projected_mrad": abs(float(sig)),
            "rms_projected_mrad": float(proj.std()),
            "fraction_beyond_3sigma_moliere": float(tail.mean()),
            "fraction_beyond_3sigma_gauss": float(2 * stats.norm.sf(3)),
        },
    }

    # Projected angle.
    fine = np.linspace(
        edges["theta_projected_mrad"][0], edges["theta_projected_mrad"][-1], 2001
    )
    mol_proj = mol.pdf_projected(fine * 1e-3) * 1e-3
    gauss = stats.norm.pdf(fine, scale=theta0)
    xa, ya, _ = density(proj_all, edges["theta_projected_mrad"])
    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=(8, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax.step(
        xa, ya, where="mid", color=C_MUTED, lw=1, label="incl. hadronic interactions"
    )
    ax.errorbar(
        x,
        y,
        yerr=yerr,
        fmt="o",
        ms=2.5,
        color=C_DATA,
        elinewidth=0.8,
        label=f"Geant4, θ$_x$ and θ$_y$ ({len(proj):,} entries)",
    )
    ax.plot(
        fine,
        mol_proj,
        color=C_THEORY,
        lw=2,
        label=f"Molière (B = {mol.B:.2f}, χ$_c$ = {mol.chi_c * 1e3:.2f} mrad)",
    )
    ax.plot(
        fine,
        gauss,
        color=C_FIT,
        lw=2,
        ls="--",
        label=f"Highland Gaussian (θ$_0$ = {theta0:.2f} mrad)",
    )
    ax.set_yscale("log")
    ax.set_ylim(bottom=0.3 / len(proj) / np.diff(edges["theta_projected_mrad"])[0])
    ax.set_ylabel("probability density [1/mrad]")
    ax.set_title(f"Projected scattering angle, {sample.name}")
    ax.legend(fontsize=8.5)
    ratio_panel(axr, x, y, yerr, mol.pdf_projected(x * 1e-3) * 1e-3, "data / Molière")
    axr.plot(fine, gauss / mol_proj, color=C_FIT, lw=1.2, ls="--")
    axr.set_xlabel("θ$_x$, θ$_y$ [mrad]")
    fig.tight_layout()
    fig.savefig(out / "scattering_projected.png", dpi=150)
    plt.close(fig)

    # Space angle.
    e = edges["theta_space_mrad"]
    x, y, yerr = density(space, e)
    fine = np.linspace(e[0], e[-1], 2001)
    mol_space = mol.pdf_space(fine * 1e-3) * 1e-3
    rayleigh = stats.rayleigh.pdf(fine, scale=theta0)
    fig, (ax, axr) = plt.subplots(
        2, 1, figsize=(8, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax.errorbar(
        x,
        y,
        yerr=yerr,
        fmt="o",
        ms=2.5,
        color=C_DATA,
        elinewidth=0.8,
        label=f"Geant4 ({len(space):,} events)",
    )
    ax.plot(fine, mol_space, color=C_THEORY, lw=2, label="Molière")
    ax.plot(
        fine,
        rayleigh,
        color=C_FIT,
        lw=2,
        ls="--",
        label=f"Highland (2D Gaussian, θ$_0$ = {theta0:.2f} mrad)",
    )
    ax.set_yscale("log")
    ax.set_ylim(bottom=0.3 / len(space) / np.diff(e)[0])
    ax.set_ylabel("probability density [1/mrad]")
    ax.set_title(f"Space scattering angle, {sample.name}")
    ax.legend(fontsize=8.5)
    ratio_panel(axr, x, y, yerr, mol.pdf_space(x * 1e-3) * 1e-3, "data / Molière")
    with np.errstate(divide="ignore", invalid="ignore"):
        axr.plot(fine, rayleigh / mol_space, color=C_FIT, lw=1.2, ls="--")
    axr.set_xlabel("θ [mrad]")
    fig.tight_layout()
    fig.savefig(out / "scattering_space.png", dpi=150)
    plt.close(fig)

    # 2D map.
    c = sample.clean
    lim = 5 * theta0
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    h = ax.hist2d(
        c["primary_theta_x"],
        c["primary_theta_y"],
        bins=120,
        range=[[-lim, lim], [-lim, lim]],
        norm=LogNorm(),
        cmap="Blues",
    )
    fig.colorbar(h[3], ax=ax, label="events")
    ax.set_xlabel("θ$_x$ [mrad]")
    ax.set_ylabel("θ$_y$ [mrad]")
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_title("Exit direction of the primary")
    fig.tight_layout()
    fig.savefig(out / "scattering_2d.png", dpi=150)
    plt.close(fig)

    return result


# --------------------------------------------------------------------------- #
# Step level
# --------------------------------------------------------------------------- #


def analyze_steps(sample: Sample, out: Path, max_events: int) -> dict | None:
    cols = [
        "track",
        "particle",
        "z_pre",
        "z_post",
        "step_len_um",
        "dekin",
        "theta_step",
        "theta_x_post",
        "theta_y_post",
    ]
    steps = sample.load_steps(cols, max_events=max_events)
    if steps is None:
        return None
    n_events = int(steps["event"].nunique())
    logger.info(f"steps: {len(steps):,} rows from {n_events:,} events")

    # Primary steps grouped by their index inside the plate rather than by z bins,
    # so steps that covered different path lengths are not mixed. Boundary steps
    # (Transportation, ~nm) carry no energy loss or deflection and are skipped.
    hadronic = set(sample.events.loc[sample.events["primary_hadronic"] == 1, "event"])
    prim = steps[
        (steps["track"] == 1)
        & (steps["step_len_um"] > 0.1)
        & ~steps["event"].isin(hadronic)
    ].copy()
    z0 = steps.loc[steps["track"] == 1, "z_pre"].min()
    prim["k"] = prim.groupby("event").cumcount()
    prim["depth_um"] = (0.5 * (prim["z_pre"] + prim["z_post"]) - z0) * 1e3
    prim["depth_post_um"] = (prim["z_post"] - z0) * 1e3
    prim["dedx"] = prim["dekin"] * 1e3 / prim["step_len_um"]

    def sigma98(v):
        v = v.to_numpy()
        lo, hi = np.quantile(v, [0.01, 0.99])
        return v[(v >= lo) & (v <= hi)].std()

    agg = prim.groupby("k").agg(
        n=("dedx", "size"),
        depth=("depth_um", "mean"),
        depth_post=("depth_post_um", "mean"),
        dekin_sum=("dekin", "sum"),
        len_sum=("step_len_um", "sum"),
        dedx_med=("dedx", "median"),
        dedx_q10=("dedx", lambda v: v.quantile(0.1)),
        dedx_q90=("dedx", lambda v: v.quantile(0.9)),
        sx=("theta_x_post", sigma98),
        sy=("theta_y_post", sigma98),
    )
    agg = agg[agg["n"] >= 0.5 * agg["n"].max()]
    # Mean as total loss over total path: a mean of per-step ratios is dominated
    # by steps cut short by a delta-electron emission.
    agg["dedx_mean"] = agg["dekin_sum"] * 1e3 / agg["len_sum"]

    beam = sample.beam
    mat = sample.material
    thickness_um = sample.thickness_mm * 1e3
    dedx_bethe = theory.bethe_mean_loss(beam, mat, 1.0) * 1e3 / 1e3  # keV/um

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    ax1.fill_between(
        agg["depth"],
        agg["dedx_q10"],
        agg["dedx_q90"],
        color=C_DATA,
        alpha=0.15,
        lw=0,
        label="10-90% of steps",
    )
    ax1.plot(agg["depth"], agg["dedx_med"], "o-", ms=3, color=C_DATA, label="median")
    ax1.plot(agg["depth"], agg["dedx_mean"], "s-", ms=3, color=C_FIT, label="mean")
    ax1.axhline(dedx_bethe, color=C_THEORY, ls="--", lw=1.5, label="Bethe <dE/dx>")
    ax1.set_xlim(0, thickness_um)
    ax1.set_xlabel("depth in the plate [µm]")
    ax1.set_ylabel("primary dE/dx in a step [keV/µm]")
    ax1.set_title("Energy loss vs depth")
    ax1.legend()

    ax2.plot(
        agg["depth_post"],
        agg["sx"],
        "o",
        ms=3,
        color=C_DATA,
        label="σ$_{98\\%}$(θ$_x$)",
    )
    ax2.plot(
        agg["depth_post"],
        agg["sy"],
        "s",
        ms=3,
        color=C_FIT2,
        label="σ$_{98\\%}$(θ$_y$)",
    )
    depths = np.linspace(5, thickness_um, 120)
    sbeam = scattering_beam(sample)
    ax2.plot(
        depths,
        [theory.highland_theta0(sbeam, mat, d * 1e-3) * 1e3 for d in depths],
        color=C_FIT,
        ls="--",
        lw=1.5,
        label="Highland θ$_0$(x)",
    )
    mol_sigma = []
    for d in depths:
        try:
            mol_sigma.append(theory.moliere(sbeam, mat, d * 1e-3).sigma_projected * 1e3)
        except ValueError:
            mol_sigma.append(np.nan)
    ax2.plot(depths, mol_sigma, color=C_THEORY, lw=1.5, label="Molière core width")
    ax2.set_xlabel("depth in the plate [µm]")
    ax2.set_ylabel("projected angle width [mrad]")
    ax2.set_title("Growth of the angular spread")
    ax2.legend()
    fig.tight_layout()
    fig.savefig(out / "depth_profile.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
    colors = [C_DATA, C_THEORY, C_FIT, C_FIT2]
    for color, p in zip(
        colors, steps["particle"].value_counts().index[:4], strict=False
    ):
        s = steps[steps["particle"] == p]
        dek = s["dekin"][s["dekin"] > 0] * 1e3
        if len(dek):
            bins = np.logspace(np.log10(dek.min()), np.log10(dek.max()), 80)
            axes[0].hist(dek, bins=bins, histtype="step", color=color, label=p)
        ang = s["theta_step"][s["theta_step"] > 0]
        if len(ang):
            bins = np.logspace(np.log10(ang.min()), np.log10(ang.max()), 80)
            axes[1].hist(ang, bins=bins, histtype="step", color=color, label=p)
        axes[2].hist(s["step_len_um"], bins=80, histtype="step", color=color, label=p)
    axes[0].set_xscale("log")
    axes[0].set_xlabel("ΔE$_{kin}$ in a step [keV]")
    axes[0].set_title("Energy loss per step")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("θ$_{step}$, deflection in a step [mrad]")
    axes[1].set_title("Deflection per step")
    axes[2].set_xlabel("step length [µm]")
    axes[2].set_title("Step length")
    for ax in axes:
        ax.set_yscale("log")
        ax.set_ylabel("steps")
        ax.legend(fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out / "step_distributions.png", dpi=150)
    plt.close(fig)

    return {"n_events": n_events, "n_steps": len(steps)}


# --------------------------------------------------------------------------- #
# Comparison with the reference sample
# --------------------------------------------------------------------------- #

COMPARE_LABELS = {
    "eloss_keV": ("primary energy loss ΔE [keV]", "linear"),
    "edep_keV": ("energy deposited in the plate [keV]", "linear"),
    "theta_projected_mrad": ("projected angle θ$_x$, θ$_y$ [mrad]", "log"),
    "theta_space_mrad": ("space angle θ [mrad]", "log"),
}


def chi2_two_samples(n1, n2):
    """Chi2 test of two unweighted histograms with different totals."""
    used = (n1 + n2) > 0
    n1, n2 = n1[used], n2[used]
    t1, t2 = n1.sum(), n2.sum()
    chi2 = float(np.sum((t2 * n1 - t1 * n2) ** 2 / (n1 + n2)) / (t1 * t2))
    ndf = int(used.sum() - 1)
    return chi2, ndf, float(stats.chi2.sf(chi2, ndf))


def compare_samples(sample: Sample, ref: Sample, edges, out: Path) -> dict:
    vals, ref_vals = sample_values(sample), sample_values(ref)
    result = {}
    for key, (xlabel, yscale) in COMPARE_LABELS.items():
        e = edges[key]
        x, y, yerr = density(vals[key], e)
        _, yr, yrerr = density(ref_vals[key], e)
        n1, _ = np.histogram(vals[key], bins=e)
        n2, _ = np.histogram(ref_vals[key], bins=e)
        chi2, ndf, p_chi2 = chi2_two_samples(n1, n2)
        ks = stats.ks_2samp(vals[key], ref_vals[key])
        result[key] = {
            "chi2": chi2,
            "ndf": ndf,
            "p_chi2": p_chi2,
            "ks_statistic": float(ks.statistic),
            "p_ks": float(ks.pvalue),
        }

        fig, (ax, axr) = plt.subplots(
            2, 1, figsize=(8, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
        )
        ax.stairs(
            yr, e, color=C_DATA, lw=1.5, label=f"{ref.name} ({len(ref_vals[key]):,})"
        )
        ax.errorbar(
            x,
            y,
            yerr=yerr,
            fmt="o",
            ms=2.5,
            color=C_THEORY,
            elinewidth=0.8,
            label=f"{sample.name} ({len(vals[key]):,})",
        )
        ax.set_yscale(yscale)
        ax.set_ylabel("probability density")
        ax.set_title(
            f"{sample.name} vs {ref.name}: χ²/ndf = {chi2:.0f}/{ndf} "
            f"(p = {p_chi2:.2g}), KS p = {ks.pvalue:.2g}",
            fontsize=10,
        )
        ax.legend()
        good = yr > 0
        r = np.full_like(y, np.nan)
        r_err = np.full_like(y, np.nan)
        r[good] = y[good] / yr[good]
        r_err[good] = r[good] * np.sqrt(
            (yerr[good] / np.where(y[good] > 0, y[good], np.inf)) ** 2
            + (yrerr[good] / yr[good]) ** 2
        )
        axr.errorbar(x, r, yerr=r_err, fmt="o", ms=2.5, color=C_THEORY, elinewidth=0.8)
        axr.axhline(1, color=C_MUTED, lw=1)
        axr.set_ylim(0.8, 1.2)
        axr.set_ylabel(f"{sample.name} / {ref.name}")
        axr.set_xlabel(xlabel)
        fig.tight_layout()
        fig.savefig(out / f"compare_{key.rsplit('_', 1)[0]}.png", dpi=150)
        plt.close(fig)
    return result


# --------------------------------------------------------------------------- #


def save_histograms(sample: Sample, edges, path: Path):
    arrays = {"n_events": len(sample.events), "n_clean": len(sample.clean)}
    for key, values in sample_values(sample).items():
        counts, _ = np.histogram(values, bins=edges[key])
        arrays[f"{key}_edges"] = edges[key]
        arrays[f"{key}_counts"] = counts
    np.savez(path, **arrays)


def analyze_sample(sample: Sample, edges, out: Path, step_events: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    n, n_clean = len(sample.events), len(sample.clean)
    beam = sample.beam
    last = sample.events["event"].max()
    logger.info(
        f"sample '{sample.name}' (events {sample.first_event}..{last}): {n:,} "
        f"events, {n_clean:,} clean ({n - len(sample.exited):,} primaries stopped "
        f"or absorbed, {len(sample.exited) - n_clean:,} with a hadronic interaction)"
    )
    summary = {
        "sample": sample.name,
        "run_tag": sample.run.tag,
        "first_event": sample.first_event,
        "last_event": int(last),
        "n_events": n,
        "n_clean": n_clean,
        "beam": {"particle": beam.name, "ekin_MeV": beam.ekin},
        "energy_loss": analyze_energy_loss(sample, edges, out),
        "scattering": analyze_scattering(sample, edges, out),
        "steps": analyze_steps(sample, out, step_events),
    }

    el_data = summary["energy_loss"]["data"]
    el_th = summary["energy_loss"]["theory"]
    logger.info(
        f"energy loss: MPV {el_data['mpv_keV']:.1f} keV "
        f"(theory {el_th['mpv_keV']:.1f}), FWHM {el_data['fwhm_keV']:.1f} keV "
        f"(Landau {el_th['fwhm_keV']:.1f}), mean {el_data['mean_keV']:.1f} keV "
        f"(Bethe {el_th['mean_bethe_keV']:.1f}), kappa {el_th['kappa']:.3f}"
    )
    sc_data = summary["scattering"]["data"]
    sc_th = summary["scattering"]["theory"]
    logger.info(
        f"scattering: core sigma {sc_data['gauss_core_sigma_projected_mrad']:.3f} "
        f"mrad (Moliere {sc_th['moliere_sigma_projected_mrad']:.3f}, Highland "
        f"{sc_th['highland_theta0_mrad']:.3f}), B = {sc_th['moliere_B']:.2f}"
    )
    save_histograms(sample, edges, out / "histograms.npz")
    return summary


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dir", default=".", help="directory with the simulation output")
    ap.add_argument("--tag", default="siplate", help="output tag of the run")
    ap.add_argument(
        "--n-reference",
        type=int,
        help="events 0..n-1 form the reference sample "
        "(default: /siplate/output/referenceEvents of the run)",
    )
    ap.add_argument("--out", default="plots", help="output directory")
    ap.add_argument(
        "--step-events",
        type=int,
        default=50_000,
        help="events read from the steps file per sample (default 50000)",
    )
    args = ap.parse_args()

    run = load_run(args.dir, args.tag)
    ref, sim = run.split(args.n_reference)
    logger.info(
        f"run '{run.tag}': {len(run.events):,} events, split {len(ref.events):,} "
        f"reference + {len(sim.events):,} simulation "
        f"({len(sim.events) / len(ref.events):.0%} of the reference)"
    )
    logger.info(
        f"{ref.beam.name} {ref.beam.ekin:.4g} MeV on {ref.thickness_mm * 1e3:.0f} µm "
        f"{ref.material.name}, physics list {run.meta['physics_list']}"
    )

    edges = make_edges(ref)
    out_run = Path(args.out) / run.tag
    for sample in (ref, sim):
        out = out_run / sample.name
        summary = analyze_sample(sample, edges, out, args.step_events)
        if sample is sim:
            summary["comparison"] = compare_samples(sim, ref, edges, out)
            for key, r in summary["comparison"].items():
                logger.info(
                    f"{sim.name} vs {ref.name}, {key}: chi2/ndf "
                    f"{r['chi2']:.1f}/{r['ndf']} (p = {r['p_chi2']:.3g}), "
                    f"KS p = {r['p_ks']:.3g}"
                )
        summary["meta"] = run.meta
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
    logger.info(f"output written to {out_run.resolve()}")


if __name__ == "__main__":
    main()
