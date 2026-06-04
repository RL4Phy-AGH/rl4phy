cmake_minimum_required(VERSION 3.16...3.30)
project(rl4phy_geant LANGUAGES CXX)

find_package(Geant4 REQUIRED ui_all vis_all)
include(${Geant4_USE_FILE})

file(GLOB sources ${PROJECT_SOURCE_DIR}/src/*.cc)
add_executable(rl4phy-geant ${sources})
target_include_directories(rl4phy-geant PRIVATE ${PROJECT_SOURCE_DIR}/src)
target_link_libraries(rl4phy-geant PRIVATE ${Geant4_LIBRARIES})
set_property(TARGET rl4phy-geant PROPERTY CXX_STANDARD 17)

# GDML import/export needs Xerces-C at runtime; on Windows the runtime DLL has a
# different name than the link lib, so bundle it next to the exe.
if(WIN32)
  add_custom_command(TARGET rl4phy-geant POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      "C:/vcpkg/installed/x64-windows/bin/xerces-c_3_3.dll"
      "$<TARGET_FILE_DIR:rl4phy-geant>"
    COMMENT "Bundling xerces-c_3_3.dll next to exe")
endif()
