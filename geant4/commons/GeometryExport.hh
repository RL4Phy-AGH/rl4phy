#pragma once

// The transport half is optional, the same way it is for the applications: a
// build without gRPC still gets WriteToFile(), just not SendOverGrpc().
#ifdef RL4PHY_ENABLE_GRPC
#include "GrpcClient.hh"
#endif

#include "G4GDMLParser.hh"
#include "G4Navigator.hh"
#include "G4TransportationManager.hh"

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

// Geometry hand-off (issue #18). G4GDMLParser::Write() takes a file name and
// nothing else - G4GDMLWrite goes through a LocalFileFormatTarget - so a file on
// the way out is unavoidable. Everything around it lives here so that no entry
// point has to know about it:
//
//   GeometryExport::SendOverGrpc(client)   write, send, clean up
//   GeometryExport::WriteToFile(path)      explicit on-disk export
//
// Kept out of GrpcClient.hh on purpose: that one is included from the per-step
// hot path, which has no business pulling in GDML and Xerces.
namespace GeometryExport
{

namespace detail
{

inline long ProcessId()
{
#ifdef _WIN32
  return static_cast<long>(_getpid());
#else
  return static_cast<long>(::getpid());
#endif
}

// tmpfs, so a geometry that is only passing through never reaches a disk.
// Anywhere without /dev/shm (i.e. not Linux) falls back to the system
// temporary directory.
inline std::filesystem::path ScratchDir()
{
  std::error_code ec;
  const std::filesystem::path shm{"/dev/shm"};
  if (std::filesystem::is_directory(shm, ec)) return shm;

  const auto tmp = std::filesystem::temp_directory_path(ec);
  return ec ? std::filesystem::path{"."} : tmp;
}

// One name per process, so two runs in parallel cannot fight over the file.
inline std::filesystem::path ScratchFile()
{
  return ScratchDir() / ("rl4phy-geometry-" + std::to_string(ProcessId()) + ".gdml");
}

inline std::string ReadFile(const std::filesystem::path& path)
{
  std::ifstream in(path, std::ios::binary);
  std::ostringstream buffer;
  buffer << in.rdbuf();
  return buffer.str();
}

}  // namespace detail

// Writes `world` - by default the current tracking world - to `path` as GDML.
// Returns false if there is no geometry to write.
//
// Two things the caller would otherwise have to know: G4GDMLWrite::Write()
// aborts the process rather than overwrite an existing file, so the path is
// cleared first; and references are switched off, which keeps volume names
// readable (Station1, ...) instead of having a pointer hash tacked onto each of
// them, because the Python side parses these names.
inline bool WriteToFile(const std::string& path, const G4VPhysicalVolume* world = nullptr)
{
  if (!world) {
    world = G4TransportationManager::GetTransportationManager()
              ->GetNavigatorForTracking()
              ->GetWorldVolume();
  }

  if (!world) {
    std::cerr << "GDML export: no world volume - is the geometry initialised?" << std::endl;
    return false;
  }

  std::error_code ec;
  std::filesystem::remove(path, ec);

  G4GDMLParser parser;
  parser.Write(path, world, false);
  return true;
}

#ifdef RL4PHY_ENABLE_GRPC

// Writes the geometry to a scratch file, hands the bytes to the Python side and
// removes the file again. Returns the number of bytes sent, 0 if anything went
// wrong; GrpcClient::SendGeometry waits for the server, so this is where a run
// pauses if the Python side is still coming up.
inline std::size_t SendOverGrpc(GrpcClient& client, const G4VPhysicalVolume* world = nullptr)
{
  const auto scratch = detail::ScratchFile();

  if (!WriteToFile(scratch.string(), world)) return 0;

  const std::string gdml = detail::ReadFile(scratch);

  std::error_code ec;
  std::filesystem::remove(scratch, ec);

  if (gdml.empty()) {
    std::cerr << "GDML export: nothing was written to " << scratch << std::endl;
    return 0;
  }

  return client.SendGeometry(gdml) ? gdml.size() : 0;
}

#endif  // RL4PHY_ENABLE_GRPC

}  // namespace GeometryExport
