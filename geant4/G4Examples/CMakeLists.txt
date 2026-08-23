#----------------------------------------------------------------------------
# Setup the project
cmake_minimum_required(VERSION 3.16...3.27)
project(G4Examples)

#----------------------------------------------------------------------------
# Find Geant4 package, activating all available UI and Vis drivers by default
# You can set WITH_GEANT4_UIVIS to OFF via the command line or ccmake/cmake-gui
# to build a batch mode only executable
#
# gdml is required rather than optional, the same way geant4/MUonE asks for it:
# commons/GeometryStream.hh is how an example hands its detector to the Python
# side, so a Geant4 without it is no use here. Asking for the component also
# brings Xerces-C into the link, which is what turns a puzzling link failure into
# a clear message at configure time.
option(WITH_GEANT4_UIVIS "Build example with Geant4 UI and Vis drivers" ON)
if(WITH_GEANT4_UIVIS)
  find_package(Geant4 REQUIRED ui_all vis_all gdml)
else()
  find_package(Geant4 REQUIRED gdml)
endif()
include(${Geant4_USE_FILE})

#----------------------------------------------------------------------------
# RL4PHYS helpers: shared gRPC plumbing and rl4phy_add_example(). The path is
# relative to this file, so it resolves whether this directory is configured
# directly or pulled in by ../CMakeLists.txt.
#
list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/../cmake)
include(RL4PhyGrpc)
include(RL4PhyExample)

#----------------------------------------------------------------------------
# One line per example: <Name>/ is the untouched upstream example and
# <Name>_rl4phys.cc our entry point. See README.md.
#
rl4phy_add_example(B1)
rl4phy_add_example(B5)
