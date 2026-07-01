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

# gRPC is optional. With it, each step is streamed to the Python side; without it
# (a plain local build, e.g. just to look at the geometry) the app still builds and
# prints the STEP records to stdout. The proto sources are generated here so the
# build does not depend on anything being pre-generated. Same spirit as the GDML
# handling above: present -> on, absent -> quietly off.
option(RL4PHY_ENABLE_GRPC "Stream step data over gRPC when available" ON)

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

    target_sources(rl4phy-geant PRIVATE
      ${RL4PHY_GEN_DIR}/rl4phy.pb.cc ${RL4PHY_GEN_DIR}/rl4phy.grpc.pb.cc)
    target_include_directories(rl4phy-geant PRIVATE ${RL4PHY_GEN_DIR})
    target_link_libraries(rl4phy-geant PRIVATE ${RL4PHY_GRPC_LIBS})
    target_compile_definitions(rl4phy-geant PRIVATE RL4PHY_ENABLE_GRPC)
  else()
    message(STATUS "gRPC/Protobuf not found: building without step streaming.")
  endif()
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
