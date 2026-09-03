#----------------------------------------------------------------------------
# RL4PhyExample - one function to turn a vendored Geant4 example into an
# RL4PHYS application:
#
#   rl4phy_add_example(<Name>)
#
# expects, next to the calling CMakeLists.txt:
#
#   <Name>/           the untouched upstream example (src/, include/, macros)
#   <Name>_rl4phys.cc our entry point, built against <Name>/include and
#                     geant4/commons
#
# and produces the executable <Name>_rl4phys with the example's macros copied
# to <build>/<Name>/ so it can be run straight from the build directory.
#
# For example, rl4phy_add_example(B5) takes B5/ and B5_rl4phys.cc, builds
# B5_rl4phys and copies B5/run1.mac and friends to <build>/B5/.
#
# Headers are added per target, never globally: B1 and B5 both ship a
# DetectorConstruction.hh, EventAction.hh, RunAction.hh, ActionInitialization.hh
# and PrimaryGeneratorAction.hh, and a global include path would let one example
# pick up the other's headers.
#----------------------------------------------------------------------------
include_guard(GLOBAL)

include(${CMAKE_CURRENT_LIST_DIR}/RL4PhyGrpc.cmake)

# geant4/commons, resolved from this file's own location the way
# RL4PhyGrpc.cmake resolves the proto directory. Cached because include_guard
# makes this file run in one directory scope only, while the function may be
# called from another.
get_filename_component(_rl4phy_commons "${CMAKE_CURRENT_LIST_DIR}/../commons" ABSOLUTE)
set(RL4PHY_COMMONS_DIR "${_rl4phy_commons}" CACHE INTERNAL "RL4PHYS shared headers")

function(rl4phy_add_example _name)
  set(_dir ${CMAKE_CURRENT_SOURCE_DIR}/${_name})
  set(_main ${CMAKE_CURRENT_SOURCE_DIR}/${_name}_rl4phys.cc)

  if(NOT EXISTS ${_main})
    message(FATAL_ERROR "rl4phy_add_example(${_name}): missing entry point ${_main}")
  endif()
  if(NOT IS_DIRECTORY ${_dir}/src)
    message(FATAL_ERROR "rl4phy_add_example(${_name}): missing upstream example directory ${_dir}")
  endif()

  file(GLOB _sources CONFIGURE_DEPENDS ${_dir}/src/*.cc)
  file(GLOB _headers CONFIGURE_DEPENDS ${_dir}/include/*.hh)

  add_executable(${_name}_rl4phys ${_main} ${_sources} ${_headers})
  # The example's own headers plus geant4/commons, so every entry point gets the
  # shared gRPC client (GrpcClient.hh) without repeating the path.
  target_include_directories(${_name}_rl4phys PRIVATE ${_dir}/include ${RL4PHY_COMMONS_DIR})
  target_link_libraries(${_name}_rl4phys PRIVATE ${Geant4_LIBRARIES})
  rl4phy_enable_grpc(${_name}_rl4phys)

  # The example's own macros and reference output, copied to <build>/<name>/ the
  # way the upstream CMakeLists does it - the executables read them from the
  # current working directory. Globbed rather than listed so a new example costs
  # no extra bookkeeping.
  file(GLOB _scripts CONFIGURE_DEPENDS
    ${_dir}/*.mac ${_dir}/*.in ${_dir}/*.out ${_dir}/*.png)
  foreach(_script ${_scripts})
    get_filename_component(_script_name ${_script} NAME)
    configure_file(${_script} ${CMAKE_CURRENT_BINARY_DIR}/${_name}/${_script_name} COPYONLY)
  endforeach()
endfunction()
