#pragma once

// The transport half is optional, the same way it is for the applications: a
// build without gRPC still gets WriteToFile(), just not SendOverGrpc().
#ifdef RL4PHY_ENABLE_GRPC
#include "GrpcClient.hh"
#endif

#include "G4GDMLParser.hh"
#include "G4Navigator.hh"
#include "G4Threading.hh"
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
//   GeometryStream::SendForRun(client)     from BeginOfRunAction, once per run
//   GeometryStream::SendOverGrpc(client)   write, send, clean up
//   GeometryStream::WriteToFile(path)      explicit on-disk export
//
// Kept out of GrpcClient.hh on purpose: that one is included from the per-step
// hot path, which has no business pulling in GDML and Xerces.
namespace GeometryStream
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

// The same hand-off, once per /run/beamOn, called from an example's own
// G4UserRunAction::BeginOfRunAction. Sending once before the macro instead is
// only right for a detector that never moves, and B5's does: its
// /B5/detector/armAngle rotates the second arm and moves it five metres
// (B5/src/DetectorConstruction.cc, SetArmAngle), three times over the course of
// B5/run1.mac. A geometry shipped before that macro would leave nine of its
// twelve events drawn on a detector they were never produced in - nothing
// fails, the picture is just wrong. A begin-of-run send picks up whatever a UI
// command changed between runs.
//
// A free function rather than a base class the way TrajectoryStream is one:
// every example already has a G4UserRunAction of its own to extend, and a
// second base class would collide with it.
//
// The thread guard is what this adds over SendOverGrpc. BeginOfRunAction fires
// on the master and on every worker, so four workers would each send their own
// copy of the same tens of kilobytes, every run. The master is the right one to
// keep: it is the thread the macro runs on, so the placements it sees are the
// ones the UI command just changed (G4VPhysicalVolume keeps its translation and
// rotation per thread), and its BeginOfRunAction runs before G4MTRunManager
// releases the workers, which is what gets the geometry on the wire ahead of
// the first event of the run it belongs to. A sequential run manager reports as
// the master too - its thread id stays G4Threading::MASTER_ID - so the same
// call is right in a single-threaded application, where it is the only thread
// there is.
//
// Returns 0 on a worker, which is also what a failed send returns; a caller
// that logs only a non-zero result therefore stays quiet on the workers, which
// is what it wants.
inline std::size_t SendForRun(GrpcClient& client, const G4VPhysicalVolume* world = nullptr)
{
  if (!G4Threading::IsMasterThread()) return 0;

  return SendOverGrpc(client, world);
}

#endif  // RL4PHY_ENABLE_GRPC

}  // namespace GeometryStream
