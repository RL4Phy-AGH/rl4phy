cmake_minimum_required(VERSION 3.16)
project(SiPlate)

find_package(Geant4 REQUIRED ui_all vis_all)
include(${Geant4_USE_FILE})

# Output format (proto/siplate.proto). Use the protobuf of the active conda
# environment, which also provides protoc and abseil.
find_package(Protobuf CONFIG REQUIRED)

file(GLOB SOURCES ${PROJECT_SOURCE_DIR}/src/*.cc)
file(GLOB HEADERS ${PROJECT_SOURCE_DIR}/include/*.hh)

add_executable(siplate main.cc ${SOURCES} ${HEADERS}
               ${PROJECT_SOURCE_DIR}/proto/siplate.proto)
target_include_directories(siplate PRIVATE ${PROJECT_SOURCE_DIR}/include
                                           ${CMAKE_CURRENT_BINARY_DIR})
target_compile_features(siplate PRIVATE cxx_std_17)
target_link_libraries(siplate ${Geant4_LIBRARIES} protobuf::libprotobuf)

# Generates siplate.pb.h / siplate.pb.cc in the build directory.
protobuf_generate(TARGET siplate LANGUAGE cpp
                  IMPORT_DIRS ${PROJECT_SOURCE_DIR}/proto
                  PROTOC_OUT_DIR ${CMAKE_CURRENT_BINARY_DIR})

# Copy the macros next to the executable, so `./siplate macros/sim.mac` works
# from the build directory. Re-run cmake after editing a macro.
file(GLOB MACROS RELATIVE ${PROJECT_SOURCE_DIR} ${PROJECT_SOURCE_DIR}/macros/*.mac)
foreach(macro ${MACROS})
  configure_file(${PROJECT_SOURCE_DIR}/${macro} ${CMAKE_BINARY_DIR}/${macro} COPYONLY)
endforeach()
