#----------------------------------------------------------------------------
# RL4PhyGrpc - gRPC/protobuf plumbing shared by every RL4PHYS application.
#
# Including this file finds the dependencies and, unless RL4PHY_ENABLE_GRPC is
# OFF, generates the stubs from proto/rl4phy.proto into the object library
# `rl4phy_proto`. Hook them up to an executable with:
#
#   rl4phy_enable_grpc(<target>)
#
# The stubs are generated once and shared: two custom commands writing the same
# OUTPUT is an error, and per-target generation would run protoc once per
# example for identical results.
#----------------------------------------------------------------------------
include_guard(GLOBAL)

# Resolved from this file's own location, so it does not matter which directory
# includes the module.
get_filename_component(RL4PHY_PROTO_DIR "${CMAKE_CURRENT_LIST_DIR}/../../proto" ABSOLUTE)

option(RL4PHY_ENABLE_GRPC "Build the RL4PHYS applications with gRPC streaming" ON)

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

  set(_gen_dir ${CMAKE_CURRENT_BINARY_DIR}/generated)
  file(MAKE_DIRECTORY ${_gen_dir})
  add_custom_command(
    OUTPUT ${_gen_dir}/rl4phy.pb.cc ${_gen_dir}/rl4phy.grpc.pb.cc
           ${_gen_dir}/rl4phy.pb.h  ${_gen_dir}/rl4phy.grpc.pb.h
    COMMAND ${RL4PHY_PROTOC}
            --proto_path=${RL4PHY_PROTO_DIR}
            --cpp_out=${_gen_dir}
            --grpc_out=${_gen_dir}
            --plugin=protoc-gen-grpc=${RL4PHY_GRPC_PLUGIN}
            ${RL4PHY_PROTO_DIR}/rl4phy.proto
    DEPENDS ${RL4PHY_PROTO_DIR}/rl4phy.proto
    COMMENT "Generating gRPC sources from rl4phy.proto")

  # An object library (not a static one): protobuf registers its descriptors
  # from static initialisers, and object files are always linked in whole.
  add_library(rl4phy_proto OBJECT
    ${_gen_dir}/rl4phy.pb.cc ${_gen_dir}/rl4phy.grpc.pb.cc)
  target_include_directories(rl4phy_proto PUBLIC ${_gen_dir})
  target_link_libraries(rl4phy_proto PUBLIC ${RL4PHY_GRPC_LIBS})
endfunction()

# Adds the generated stubs, their include directory and the gRPC libraries to
# <target>, and defines RL4PHY_ENABLE_GRPC for its sources. A no-op when the
# build was configured without gRPC.
function(rl4phy_enable_grpc _target)
  if(TARGET rl4phy_proto)
    target_link_libraries(${_target} PRIVATE rl4phy_proto)
    target_compile_definitions(${_target} PRIVATE RL4PHY_ENABLE_GRPC)
  endif()
endfunction()

if(RL4PHY_ENABLE_GRPC)
  rl4phy_setup_grpc()
endif()
