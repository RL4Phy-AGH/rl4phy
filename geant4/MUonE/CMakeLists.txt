cmake_minimum_required(VERSION 3.16...3.30)
project(rl4phy_geant LANGUAGES CXX)

# gdml is a required component here: it is how we hand the geometry over to the
# Python side, so a build without it is no use to us. Asking Geant4 for the
# component (rather than test-compiling the header) also brings Xerces-C into the
# link, and it does not get fooled the way a header probe does when the linker
# cannot see Xerces yet.
find_package(Geant4 REQUIRED ui_all vis_all gdml)
include(${Geant4_USE_FILE})

file(GLOB sources CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cc)
add_executable(rl4phy-geant main.cc ${sources})
target_include_directories(rl4phy-geant PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(rl4phy-geant PRIVATE ${Geant4_LIBRARIES})
set_property(TARGET rl4phy-geant PROPERTY CXX_STANDARD 17)

if(Geant4_gdml_FOUND)
  target_compile_definitions(rl4phy-geant PRIVATE RL4PHY_ENABLE_GDML)
endif()

# GDML import/export needs Xerces-C at runtime; on Windows the runtime DLL has a
# different name than the link lib, so bundle it next to the exe when the file
# is actually present in the expected vcpkg location.
if(WIN32 AND EXISTS "C:/vcpkg/installed/x64-windows/bin/xerces-c_3_3.dll")
  add_custom_command(TARGET rl4phy-geant POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      "C:/vcpkg/installed/x64-windows/bin/xerces-c_3_3.dll"
      "$<TARGET_FILE_DIR:rl4phy-geant>"
    COMMENT "Bundling xerces-c_3_3.dll next to exe")
endif()
