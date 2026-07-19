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
# Setup include directory for this project
#
include(${Geant4_USE_FILE})
include_directories(${PROJECT_SOURCE_DIR}/B1/include)

#----------------------------------------------------------------------------
# Locate sources and headers for this project
# NB: headers are included so they will show up in IDEs
#
file(GLOB sources_B1 ${PROJECT_SOURCE_DIR}/B1/src/*.cc)
file(GLOB headers_B1 ${PROJECT_SOURCE_DIR}/B1/include/*.hh)

#----------------------------------------------------------------------------
# Add the executable, and link it to the Geant4 libraries
#
add_executable(B1_rl4phys B1_rl4phys.cc ${sources_B1} ${headers_B1})
target_link_libraries(B1_rl4phys PRIVATE ${Geant4_LIBRARIES})

#----------------------------------------------------------------------------
# gRPC (optional): stream per-event B1 scoring over rl4phy.proto
#
option(RL4PHY_ENABLE_GRPC "Build B1_rl4phys with gRPC streaming" ON)

if(RL4PHY_ENABLE_GRPC)
  find_package(Protobuf CONFIG QUIET)
  if(NOT Protobuf_FOUND)
    find_package(Protobuf QUIET)
  endif()
  find_package(gRPC CONFIG QUIET)

  if(gRPC_FOUND)
    set(RL4PHY_GRPC_LIBS gRPC::grpc++)
    set(RL4PHY_GRPC_PLUGIN $<TARGET_FILE:gRPC::grpc_cpp_plugin>)
  else()
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

  if(Protobuf_FOUND AND RL4PHY_PROTOC AND RL4PHY_GRPC_PLUGIN AND (gRPC_FOUND OR RL4PHY_GRPCPP))
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

    target_sources(B1_rl4phys PRIVATE
      ${RL4PHY_GEN_DIR}/rl4phy.pb.cc ${RL4PHY_GEN_DIR}/rl4phy.grpc.pb.cc)
    target_include_directories(B1_rl4phys PRIVATE ${RL4PHY_GEN_DIR})
    target_link_libraries(B1_rl4phys PRIVATE ${RL4PHY_GRPC_LIBS})
    target_compile_definitions(B1_rl4phys PRIVATE RL4PHY_ENABLE_GRPC)
  else()
    message(FATAL_ERROR "gRPC/Protobuf required for B1_rl4phys (set RL4PHY_ENABLE_GRPC=OFF to skip).")
  endif()
endif()

#----------------------------------------------------------------------------
# Copy all scripts to the build directory, i.e. the directory in which we
# build B1. This is so that we can run the executable directly because it
# relies on these scripts being in the current working directory.
#
set(EXAMPLE_SCRIPTS
  B1/exampleB1.in
  B1/exampleB1.out
  B1/init_vis.mac
  B1/run1.mac
  B1/run2.mac
  B1/vis.mac
  )

foreach(_script ${EXAMPLE_SCRIPTS})
  configure_file(
    ${PROJECT_SOURCE_DIR}/${_script}
    ${PROJECT_BINARY_DIR}/${_script}
    COPYONLY
    )
endforeach()
