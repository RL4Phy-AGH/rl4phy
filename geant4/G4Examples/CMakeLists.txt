#----------------------------------------------------------------------------
# Setup the project
cmake_minimum_required(VERSION 3.16...3.27)
project(G4Examples)

#----------------------------------------------------------------------------
# Find Geant4 package, activating all available UI and Vis drivers by default
# You can set WITH_GEANT4_UIVIS to OFF via the command line or ccmake/cmake-gui
# to build a batch mode only executable
#
option(WITH_GEANT4_UIVIS "Build example with Geant4 UI and Vis drivers" ON)
if(WITH_GEANT4_UIVIS)
  find_package(Geant4 REQUIRED ui_all vis_all)
else()
  find_package(Geant4 REQUIRED)
endif()

#----------------------------------------------------------------------------
# Setup Geant4 include directories and compile definitions
#
# NB: the per-example headers are NOT added globally. B1 and B5 both ship a
# DetectorConstruction.hh, EventAction.hh, RunAction.hh, ActionInitialization.hh
# and PrimaryGeneratorAction.hh; a global include path would let one example pick
# up the other's headers. Each target gets its own include directory instead,
# the way the upstream B5 example does it.
#
include(${Geant4_USE_FILE})

#----------------------------------------------------------------------------
# gRPC (optional): stream scoring data over rl4phy.proto
#
# Every example here speaks the same proto, so the stubs are generated once into
# an object library and shared. Generating them per target would mean two custom
# commands writing the same OUTPUT, which CMake rejects. rl4phy_setup_grpc()
# does the discovery and the generation; rl4phy_enable_grpc(<target>) hooks the
# result up to one executable.
#
option(RL4PHY_ENABLE_GRPC "Build the rl4phys examples with gRPC streaming" ON)

function(rl4phy_setup_grpc)
  find_package(Protobuf CONFIG QUIET)
  if(NOT Protobuf_FOUND)
    find_package(Protobuf QUIET)
  endif()
  find_package(gRPC CONFIG QUIET)

  if(gRPC_FOUND)
    set(RL4PHY_GRPC_LIBS gRPC::grpc++)
    set(RL4PHY_GRPC_PLUGIN $<TARGET_FILE:gRPC::grpc_cpp_plugin>)
  else()
    # Debian/Ubuntu ship the libraries and the plugin without a CMake config.
    find_library(RL4PHY_GRPCPP NAMES grpc++)
    find_library(RL4PHY_GRPC NAMES grpc)
    find_library(RL4PHY_GPR NAMES gpr)
    find_program(RL4PHY_GRPC_PLUGIN NAMES grpc_cpp_plugin)
    set(RL4PHY_GRPC_LIBS ${RL4PHY_GRPCPP} ${RL4PHY_GRPC} ${RL4PHY_GPR})
  endif()

  if(TARGET protobuf::protoc)
    set(RL4PHY_PROTOC $<TARGET_FILE:protobuf::protoc>)
  else()
    find_program(RL4PHY_PROTOC NAMES protoc)
  endif()

  if(TARGET protobuf::libprotobuf)
    list(APPEND RL4PHY_GRPC_LIBS protobuf::libprotobuf)
  else()
    list(APPEND RL4PHY_GRPC_LIBS ${Protobuf_LIBRARIES})
  endif()

  if(NOT (Protobuf_FOUND AND RL4PHY_PROTOC AND RL4PHY_GRPC_PLUGIN AND (gRPC_FOUND OR RL4PHY_GRPCPP)))
    message(FATAL_ERROR "gRPC/Protobuf required for the rl4phys examples (set RL4PHY_ENABLE_GRPC=OFF to skip).")
  endif()

  set(RL4PHY_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../proto)
  set(RL4PHY_GEN_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
  file(MAKE_DIRECTORY ${RL4PHY_GEN_DIR})
  add_custom_command(
    OUTPUT ${RL4PHY_GEN_DIR}/rl4phy.pb.cc ${RL4PHY_GEN_DIR}/rl4phy.grpc.pb.cc
           ${RL4PHY_GEN_DIR}/rl4phy.pb.h  ${RL4PHY_GEN_DIR}/rl4phy.grpc.pb.h
    COMMAND ${RL4PHY_PROTOC}
            --proto_path=${RL4PHY_PROTO_DIR}
            --cpp_out=${RL4PHY_GEN_DIR}
            --grpc_out=${RL4PHY_GEN_DIR}
            --plugin=protoc-gen-grpc=${RL4PHY_GRPC_PLUGIN}
            ${RL4PHY_PROTO_DIR}/rl4phy.proto
    DEPENDS ${RL4PHY_PROTO_DIR}/rl4phy.proto
    COMMENT "Generating gRPC sources from rl4phy.proto")

  # An object library (not a static one): protobuf registers its descriptors from
  # static initialisers, and object files are always linked in whole.
  add_library(rl4phy_proto OBJECT
    ${RL4PHY_GEN_DIR}/rl4phy.pb.cc ${RL4PHY_GEN_DIR}/rl4phy.grpc.pb.cc)
  target_include_directories(rl4phy_proto PUBLIC ${RL4PHY_GEN_DIR})
  target_link_libraries(rl4phy_proto PUBLIC ${RL4PHY_GRPC_LIBS})
endfunction()

function(rl4phy_enable_grpc _target)
  if(TARGET rl4phy_proto)
    target_link_libraries(${_target} PRIVATE rl4phy_proto)
    target_compile_definitions(${_target} PRIVATE RL4PHY_ENABLE_GRPC)
  endif()
endfunction()

if(RL4PHY_ENABLE_GRPC)
  rl4phy_setup_grpc()
endif()

#----------------------------------------------------------------------------
# Locate sources and headers for each example
# NB: headers are included so they will show up in IDEs
#
file(GLOB sources_B1 ${PROJECT_SOURCE_DIR}/B1/src/*.cc)
file(GLOB headers_B1 ${PROJECT_SOURCE_DIR}/B1/include/*.hh)

file(GLOB sources_B5 ${PROJECT_SOURCE_DIR}/B5/src/*.cc)
file(GLOB headers_B5 ${PROJECT_SOURCE_DIR}/B5/include/*.hh)

#----------------------------------------------------------------------------
# Add the executables, use their own headers, and link them to the Geant4
# libraries
#
add_executable(B1_rl4phys B1_rl4phys.cc ${sources_B1} ${headers_B1})
target_include_directories(B1_rl4phys PRIVATE ${PROJECT_SOURCE_DIR}/B1/include)
target_link_libraries(B1_rl4phys PRIVATE ${Geant4_LIBRARIES})
rl4phy_enable_grpc(B1_rl4phys)

add_executable(B5_rl4phys B5_rl4phys.cc ${sources_B5} ${headers_B5})
target_include_directories(B5_rl4phys PRIVATE ${PROJECT_SOURCE_DIR}/B5/include)
target_link_libraries(B5_rl4phys PRIVATE ${Geant4_LIBRARIES})
rl4phy_enable_grpc(B5_rl4phys)

#----------------------------------------------------------------------------
# Copy all scripts to the build directory, i.e. the directory in which we
# build the examples. This is so that we can run the executables directly
# because they rely on these scripts being in the current working directory.
#
set(EXAMPLE_SCRIPTS
  B1/exampleB1.in
  B1/exampleB1.out
  B1/init_vis.mac
  B1/run1.mac
  B1/run2.mac
  B1/vis.mac
  B5/exampleB5.in
  B5/init_vis.mac
  B5/run1.mac
  B5/run2.mac
  B5/vis.mac
  B5/gui.mac
  B5/icons.mac
  B5/plotter.mac
  B5/tsg_offscreen.mac
  )

foreach(_script ${EXAMPLE_SCRIPTS})
  configure_file(
    ${PROJECT_SOURCE_DIR}/${_script}
    ${PROJECT_BINARY_DIR}/${_script}
    COPYONLY
    )
endforeach()
