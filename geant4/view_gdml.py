#!/usr/bin/env python3

import argparse
import os

import pyg4ometry.gdml as gdml
import pyg4ometry.visualisation as vis


def print_geometry_summary(registry):

    print("\n========== GEOMETRY SUMMARY ==========")

    for name, lv in registry.logicalVolumeDict.items():
        solid = getattr(lv, "solid", None)
        material = getattr(lv, "material", None)

        print(name)

        if solid:
            print(f"  Solid: {solid.name}")
            print(f"  Type: {type(solid).__name__}")

        if material:
            print(f"  Material: {material.name}")

        if hasattr(lv, "daughterVolumes"):
            print(f"  Daughters: {len(lv.daughterVolumes)}")

        print("-------------------------------------")

    print("=====================================\n")


def set_visual_options(lv, args):

    material = getattr(lv, "material", None)

    matname = ""

    if material:
        matname = material.name.upper()

    vo = vis.VisualisationOptions()

    # defaults

    vo.visible = True
    vo.alpha = args.opacity
    vo.representation = "surface"
    vo.colour = [0.5, 0.5, 0.5]

    # hide air/world

    if args.hide_world:
        if "AIR" in matname:
            vo.visible = False

    # wireframe

    if args.wireframe:
        vo.representation = "wireframe"

    # material colours

    if "WATER" in matname:
        vo.colour = [0.2, 0.4, 1.0]
        vo.alpha = 0.25

    elif "BONE" in matname:
        vo.colour = [0.9, 0.8, 0.6]
        vo.alpha = 1.0

    elif "TISSUE" in matname:
        vo.colour = [1.0, 0.5, 0.6]
        vo.alpha = 0.9

    elif "AIR" in matname:
        vo.colour = [0.7, 0.7, 0.7]

    lv.visOptions = vo

    print(
        f"VIS {lv.name}: "
        f"visible={vo.visible}, "
        f"alpha={vo.alpha}, "
        f"repr={vo.representation}, "
        f"material={matname}"
    )


def configure_geometry_visibility(registry, args):

    print("\nApplying visual options...\n")

    for name, lv in registry.logicalVolumeDict.items():
        set_visual_options(lv, args)

    print()


def main():

    parser = argparse.ArgumentParser(
        description="GDML detector viewer using pyg4ometry"
    )

    parser.add_argument("gdml_file")

    parser.add_argument(
        "--hide-world", action="store_true", help="hide volumes made of G4_AIR"
    )

    parser.add_argument("--wireframe", action="store_true", help="wireframe rendering")

    parser.add_argument("--opacity", type=float, default=0.6)

    parser.add_argument("--zoom", type=float, default=2.0)

    args = parser.parse_args()

    if not os.path.isfile(args.gdml_file):
        raise FileNotFoundError(args.gdml_file)

    print(f"Loading GDML geometry: {args.gdml_file}")

    reader = gdml.Reader(args.gdml_file)

    registry = reader.getRegistry()

    world = registry.getWorldVolume()

    print("\nWorld volume:")
    print(" ", world.name)

    print_geometry_summary(registry)

    #
    # IMPORTANT:
    # set vis options BEFORE adding geometry
    #

    configure_geometry_visibility(registry, args)

    print("Creating VTK viewer...")

    viewer = vis.VtkViewerNew()

    print("Initialising VTK...")

    viewer.initVtk()

    print("Adding world volume...")

    viewer.addLogicalVolume(world)

    print("Building pipelines...")

    viewer.buildPipelinesAppend()

    print("Exporting VTP...")

    try:
        viewer.exportVTPScene("detector_geometry.vtp")

        print("detector_geometry.vtp created")

    except Exception as e:
        print("VTP export failed:", e)

    viewer.addAxes()

    print("Rendering...")

    viewer.render()

    try:
        viewer.ren.ResetCamera()
        viewer.ren.ResetCameraClippingRange()

        viewer.ren.GetActiveCamera().Zoom(args.zoom)

    except Exception as e:
        print("Camera setup failed:", e)

    print("Starting viewer...")

    viewer.iren.Initialize()
    viewer.iren.Start()


if __name__ == "__main__":
    main()
