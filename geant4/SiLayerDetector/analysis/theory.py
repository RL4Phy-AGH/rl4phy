"""Theory predictions for a charged particle crossing a thin layer of material.

Energy loss (PDG Review of Particle Physics, "Passage of particles through
matter"):
  - Bethe mean energy loss with the Sternheimer density-effect correction,
  - Landau width parameter xi and the Landau-Vavilov-Bichsel most probable
    energy loss, together with the universal Landau function, which gives the
    shape of the distribution for kappa = xi / T_max << 1.

Multiple Coulomb scattering:
  - Highland's Gaussian approximation (PDG),
  - Moliere theory in Bethe's formulation (Phys. Rev. 89 (1953) 1256), with the
    screening angle and compound-material rules of Gottschalk et al.,
    Nucl. Instrum. Meth. B 74 (1993) 467. Both the projected (theta_x) and the
    space-angle (theta) distributions are provided.

Material constants come from the run header of <tag>.pb (see siplate_io.py), so
nothing here is specific to silicon. Units: MeV, mm, g/cm3, rad.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from scipy import integrate, optimize, special, stats

K_BETHE = 0.307075  # MeV mol^-1 cm^2
M_E = 0.51099895  # MeV
ALPHA = 1 / 137.035999
LN10 = np.log(10.0)

# PDG code -> (name, mass [MeV], charge [e])
PARTICLES = {
    2212: ("proton", 938.272089, 1),
    -2212: ("anti_proton", 938.272089, -1),
    11: ("e-", M_E, -1),
    -11: ("e+", M_E, 1),
    13: ("mu-", 105.6583755, -1),
    -13: ("mu+", 105.6583755, 1),
    211: ("pi+", 139.57039, 1),
    -211: ("pi-", 139.57039, -1),
    321: ("kaon+", 493.677, 1),
    -321: ("kaon-", 493.677, -1),
    1000020040: ("alpha", 3727.3794, 2),
}


# --------------------------------------------------------------------------- #
# Material and beam
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Element:
    z: float
    a: float  # g/mol
    mass_fraction: float


@dataclass(frozen=True)
class Material:
    name: str
    density: float  # g/cm3
    radiation_length_mm: float
    mean_excitation_mev: float
    density_effect: dict
    elements: tuple[Element, ...]

    @classmethod
    def from_meta(cls, meta: dict) -> Material:
        m = meta["material"]
        return cls(
            name=m["name"],
            density=m["density_g_cm3"],
            radiation_length_mm=m["radiation_length_mm"],
            mean_excitation_mev=m["mean_excitation_eV"] * 1e-6,
            density_effect=m["density_effect"],
            elements=tuple(
                Element(e["Z"], e["A_g_mol"], e["mass_fraction"]) for e in m["elements"]
            ),
        )

    @property
    def z_over_a(self) -> float:
        return sum(e.mass_fraction * e.z / e.a for e in self.elements)


@dataclass(frozen=True)
class Beam:
    name: str
    mass: float  # MeV
    charge: int
    ekin: float  # MeV

    @classmethod
    def from_pdg(cls, pdg: int, ekin: float, mass: float | None = None) -> Beam:
        if pdg in PARTICLES:
            name, m, q = PARTICLES[pdg]
        elif mass is None:
            raise ValueError(f"unknown PDG code {pdg}: pass the mass explicitly")
        else:
            name, m, q = str(pdg), mass, 1
        return cls(name, mass if mass is not None else m, q, ekin)

    def at(self, ekin: float) -> Beam:
        return Beam(self.name, self.mass, self.charge, ekin)

    @property
    def energy(self) -> float:
        return self.ekin + self.mass

    @property
    def momentum(self) -> float:
        return np.sqrt(self.energy**2 - self.mass**2)

    @property
    def gamma(self) -> float:
        return self.energy / self.mass

    @property
    def beta(self) -> float:
        return self.momentum / self.energy

    @property
    def betagamma(self) -> float:
        return self.momentum / self.mass


def areal_density(mat: Material, thickness_mm: float) -> float:
    """Thickness in g/cm2."""
    return mat.density * thickness_mm * 0.1


# --------------------------------------------------------------------------- #
# Energy loss
# --------------------------------------------------------------------------- #


def density_correction(beam: Beam, mat: Material) -> float:
    """Sternheimer density-effect correction delta(beta*gamma)."""
    d = mat.density_effect
    x = np.log10(beam.betagamma)
    if x >= d["x1"]:
        return 2 * LN10 * x - d["C"]
    if x >= d["x0"]:
        return 2 * LN10 * x - d["C"] + d["a"] * (d["x1"] - x) ** d["m"]
    return d["delta0"] * 10 ** (2 * (x - d["x0"]))


def t_max(beam: Beam) -> float:
    """Maximum energy transfer to a free electron in one collision [MeV]."""
    r = M_E / beam.mass
    bg2 = beam.betagamma**2
    return 2 * M_E * bg2 / (1 + 2 * beam.gamma * r + r**2)


def bethe_mean_loss(beam: Beam, mat: Material, thickness_mm: float) -> float:
    """Mean energy loss in the layer from the Bethe formula [MeV]."""
    b2, bg2 = beam.beta**2, beam.betagamma**2
    i = mat.mean_excitation_mev
    log_term = 0.5 * np.log(2 * M_E * bg2 * t_max(beam) / i**2)
    stopping = (
        K_BETHE
        * beam.charge**2
        * mat.z_over_a
        / b2
        * (log_term - b2 - density_correction(beam, mat) / 2)
    )
    return stopping * areal_density(mat, thickness_mm)


def landau_xi(beam: Beam, mat: Material, thickness_mm: float) -> float:
    """Landau width parameter xi [MeV]."""
    return (
        K_BETHE
        / 2
        * mat.z_over_a
        * beam.charge**2
        * areal_density(mat, thickness_mm)
        / beam.beta**2
    )


def landau_mpv(beam: Beam, mat: Material, thickness_mm: float) -> float:
    """Landau-Vavilov-Bichsel most probable energy loss [MeV] (PDG, j = 0.200)."""
    xi = landau_xi(beam, mat, thickness_mm)
    i = mat.mean_excitation_mev
    bg2 = beam.betagamma**2
    return xi * (
        np.log(2 * M_E * bg2 / i)
        + np.log(xi / i)
        + 0.200
        - beam.beta**2
        - density_correction(beam, mat)
    )


def landau_kappa(beam: Beam, mat: Material, thickness_mm: float) -> float:
    """kappa = xi / T_max. Landau regime for kappa < ~0.01, Vavilov up to ~10."""
    return landau_xi(beam, mat, thickness_mm) / t_max(beam)


# scipy.stats.landau is the stable distribution in Nolan's parametrisation. The
# physics Landau function phi(lambda) = 1/pi int exp(-u ln u - lambda u) sin(pi u)
# du is the same curve stretched by pi/2: phi(lambda) = S(lambda / s + c) / s with
# s = pi/2 (checked numerically against the integral to 1e-7). Only the scale
# matters here, because the curve is always placed by its peak.
_SCIPY_LANDAU_SCALE = np.pi / 2


@cache
def _scipy_landau_shape() -> tuple[float, float]:
    """Mode and FWHM of scipy's standard Landau density."""
    pdf = stats.landau.pdf
    mode = optimize.minimize_scalar(lambda x: -pdf(x), bracket=(-1, 0, 1)).x
    half = pdf(mode) / 2
    lo = optimize.brentq(lambda x: pdf(x) - half, mode - 10, mode)
    hi = optimize.brentq(lambda x: pdf(x) - half, mode, mode + 20)
    return float(mode), float(hi - lo)


def landau_fwhm_in_xi() -> float:
    """FWHM of the Landau distribution in units of xi, about 4.02."""
    return _scipy_landau_shape()[1] * _SCIPY_LANDAU_SCALE


def landau_pdf(delta, mpv: float, xi: float):
    """Landau density of the energy loss delta, peaked at mpv, scale xi [1/MeV]."""
    scale = xi * _SCIPY_LANDAU_SCALE
    x = (np.asarray(delta) - mpv) / scale + _scipy_landau_shape()[0]
    return stats.landau.pdf(x) / scale


# Gauss-Hermite nodes for the Landau (x) Gauss convolution.
_GH_NODES, _GH_WEIGHTS = np.polynomial.hermite.hermgauss(48)


def langaus_pdf(delta, mpv: float, xi: float, sigma: float):
    """Landau density convolved with a Gaussian of width sigma [1/MeV].

    The Gaussian absorbs effects the Landau function leaves out, mostly atomic
    binding in thin layers. mpv is the Landau peak before the convolution.
    """
    delta = np.asarray(delta, dtype=float)
    shifts = np.sqrt(2) * abs(sigma) * _GH_NODES
    vals = landau_pdf(delta[..., None] - shifts, mpv, xi)
    return vals @ _GH_WEIGHTS / np.sqrt(np.pi)


# --------------------------------------------------------------------------- #
# Multiple scattering
# --------------------------------------------------------------------------- #


def highland_theta0(beam: Beam, mat: Material, thickness_mm: float) -> float:
    """Width of the projected angle from Highland's formula (PDG) [rad]."""
    x = thickness_mm / mat.radiation_length_mm
    z = beam.charge
    pv = beam.beta * beam.momentum
    return (
        13.6 / pv * abs(z) * np.sqrt(x) * (1 + 0.038 * np.log(x * z**2 / beam.beta**2))
    )


@dataclass(frozen=True)
class Moliere:
    """Moliere distribution for one beam, material and thickness.

    chi_c: single-scattering characteristic angle [rad]
    chi_a: screening angle [rad]
    B: solution of B - ln B = ln(chi_c^2 / (1.167 chi_a^2)); the expansion is
       reliable for B >~ 4.5.
    """

    chi_c: float
    chi_a: float
    B: float

    @property
    def theta_m(self) -> float:
        """Moliere's characteristic angle chi_c * sqrt(B) [rad]."""
        return self.chi_c * np.sqrt(self.B)

    @property
    def theta_1e(self) -> float:
        """Space angle where the Gaussian core falls to 1/e [rad]."""
        return self.chi_c * np.sqrt(self.B - 1.2)

    @property
    def sigma_projected(self) -> float:
        """Width of the Gaussian core of the projected distribution [rad]."""
        return self.theta_1e / np.sqrt(2)

    def pdf_projected(self, theta):
        """Density of the projected angle theta_x [1/rad]."""
        t = np.abs(np.asarray(theta, dtype=float)) / self.theta_m
        g0, g1, g2 = _universal("projected", t)
        return (g0 + g1 / self.B + g2 / self.B**2) / self.theta_m

    def pdf_space(self, theta):
        """Density of the space angle theta per unit theta [1/rad]."""
        theta = np.asarray(theta, dtype=float)
        t = theta / self.theta_m
        f0, f1, f2 = _universal("space", t)
        return theta / self.theta_m**2 * (f0 + f1 / self.B + f2 / self.B**2)


def moliere(beam: Beam, mat: Material, thickness_mm: float) -> Moliere:
    """Moliere parameters (Gottschalk et al. 1993, eqs. for chi_c, chi_a, B)."""
    z = beam.charge
    p = beam.momentum
    pv = beam.beta * p
    t = areal_density(mat, thickness_mm)

    # Weights Z(Z+1)/A per element: scattering on nuclei and atomic electrons.
    w = np.array([e.mass_fraction * e.z * (e.z + 1) / e.a for e in mat.elements])
    chi_c2 = 0.157 * z**2 * t / pv**2 * w.sum()
    chi_a2_el = np.array(
        [
            2.007e-5
            * e.z ** (2 / 3)
            * (1 + 3.34 * (e.z * z * ALPHA / beam.beta) ** 2)
            / p**2
            for e in mat.elements
        ]
    )
    chi_a2 = np.exp(np.sum(w * np.log(chi_a2_el)) / w.sum())

    b = np.log(chi_c2 / (1.167 * chi_a2))
    if b <= 1:
        raise ValueError(f"layer too thin for Moliere theory (b = {b:.2f})")
    big_b = optimize.brentq(lambda x: x - np.log(x) - b, 1.0 + 1e-9, 2 * b + 10)
    return Moliere(np.sqrt(chi_c2), np.sqrt(chi_a2), big_b)


# Bethe's universal functions, tabulated once and interpolated. For the space
# angle (reduced variable v = theta / theta_m):
#   f_n(v) = 1/n! int_0^inf u J0(v u) exp(-u^2/4) [u^2/4 ln(u^2/4)]^n du,
# so f_0 = 2 exp(-v^2) and the density per dv is v [f_0 + f_1/B + f_2/B^2].
# The projected analogue replaces the Hankel transform by a cosine transform:
#   g_n(v) = 1/(pi n!) int_0^inf cos(v u) exp(-u^2/4) [u^2/4 ln(u^2/4)]^n du,
# so g_0 = exp(-v^2)/sqrt(pi), already a density per dv.
_V_MAX = 40.0
_U_MAX = 14.0  # exp(-u^2/4) is negligible beyond


def _kernel(u, n):
    s = u * u / 4
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(s > 0, s * np.log(s), 0.0)
    return np.exp(-s) * corr**n / special.factorial(n)


_TABLE_CACHE = Path.home() / ".cache" / "siplate" / "moliere_tables_v1.npz"


@cache
def _tables() -> dict[str, np.ndarray]:
    """Tables of f_1, f_2, g_1, g_2. Computing them takes ~30 s, so they are
    kept in ~/.cache/siplate and reused."""
    if _TABLE_CACHE.exists():
        with np.load(_TABLE_CACHE) as data:
            return dict(data)
    out = _compute_tables()
    try:
        _TABLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(_TABLE_CACHE, **out)
    except OSError:
        pass
    return out


def _compute_tables() -> dict[str, np.ndarray]:
    v = np.concatenate([np.linspace(0, 10, 801), np.linspace(10.05, _V_MAX, 600)])
    out = {}
    for n in (1, 2):
        proj = [
            integrate.quad(
                _kernel, 0, _U_MAX, args=(n,), weight="cos", wvar=x, limit=400
            )[0]
            / np.pi
            for x in v
        ]
        space = [
            integrate.quad(
                lambda u, x=x, n=n: u * special.j0(x * u) * _kernel(u, n),
                0,
                _U_MAX,
                limit=800,
            )[0]
            for x in v
        ]
        out[f"projected{n}"] = np.array(proj)
        out[f"space{n}"] = np.array(space)
    out["v"] = v
    return out


def _universal(kind: str, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tab = _tables()
    grid = tab["v"]
    f1 = np.interp(v, grid, tab[f"{kind}1"], right=np.nan)
    f2 = np.interp(v, grid, tab[f"{kind}2"], right=np.nan)
    f0 = (
        np.exp(-(v**2)) / np.sqrt(np.pi) if kind == "projected" else 2 * np.exp(-(v**2))
    )
    return f0, f1, f2
