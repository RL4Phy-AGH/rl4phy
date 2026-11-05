#include "RecordFile.hh"

#include "siplate.pb.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <memory>
#include <queue>
#include <vector>

namespace fs = std::filesystem;

namespace {

// Files named exactly <base>_part<digits>.bin in the working directory.
std::vector<fs::path> Parts(const std::string& base) {
  const std::string prefix = fs::path(base).filename().string() + "_part";
  std::vector<fs::path> files;
  for (const auto& entry : fs::directory_iterator(fs::current_path())) {
    if (!entry.is_regular_file() || entry.path().extension() != ".bin") continue;
    const std::string stem = entry.path().stem().string();
    if (stem.rfind(prefix, 0) != 0 || stem.size() == prefix.size()) continue;
    const bool digits = std::all_of(stem.begin() + prefix.size(), stem.end(),
                                    [](unsigned char c) { return std::isdigit(c); });
    if (digits) files.push_back(entry.path());
  }
  std::sort(files.begin(), files.end());
  return files;
}

void WriteU32(std::ostream& out, std::uint32_t v) {
  char b[4];
  for (int i = 0; i < 4; ++i) b[i] = static_cast<char>((v >> (8 * i)) & 0xff);
  out.write(b, 4);
}

bool ReadU32(std::istream& in, std::uint32_t& v) {
  unsigned char b[4];
  if (!in.read(reinterpret_cast<char*>(b), 4)) return false;
  v = b[0] | (b[1] << 8) | (b[2] << 16) | (static_cast<std::uint32_t>(b[3]) << 24);
  return true;
}

void WriteVarint(std::ostream& out, std::uint64_t v) {
  while (v >= 0x80) {
    out.put(static_cast<char>((v & 0x7f) | 0x80));
    v >>= 7;
  }
  out.put(static_cast<char>(v));
}

void WriteRecord(std::ostream& out, const siplate::Record& record) {
  const std::string bytes = record.SerializeAsString();
  WriteVarint(out, bytes.size());
  out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

std::size_t VarintSize(std::uint64_t v) {
  std::size_t n = 1;
  while (v >= 0x80) {
    v >>= 7;
    ++n;
  }
  return n;
}

struct Part {
  std::ifstream in;
  std::uint32_t event = 0;
  std::string bytes;

  bool Next() {
    std::uint32_t size = 0;
    if (!ReadU32(in, event) || !ReadU32(in, size)) return false;
    bytes.resize(size);
    return static_cast<bool>(in.read(bytes.data(), size));
  }
};

}  // namespace

namespace RecordFile {

std::string PartPath(const std::string& base, int threadID) {
  return base + "_part" + std::to_string(threadID) + ".bin";
}

void RemoveParts(const std::string& base) {
  for (const auto& f : Parts(base)) fs::remove(f);
}

void WriteEventFrame(std::ofstream& out, std::int32_t eventID,
                     const std::string& eventBytes) {
  WriteU32(out, static_cast<std::uint32_t>(eventID));
  WriteU32(out, static_cast<std::uint32_t>(eventBytes.size()));
  out.write(eventBytes.data(), static_cast<std::streamsize>(eventBytes.size()));
}

long Merge(const std::string& base, const siplate::Record& header) {
  const auto files = Parts(base);
  std::vector<std::unique_ptr<Part>> parts;
  for (const auto& f : files) {
    auto part = std::make_unique<Part>();
    part->in.open(f, std::ios::binary);
    if (part->Next()) parts.push_back(std::move(part));
  }

  std::ofstream out(base + ".pb", std::ios::binary);
  WriteRecord(out, header);

  // Min-heap on (event ID, part index); each part is sorted by event already.
  using Entry = std::pair<std::uint32_t, std::size_t>;
  std::priority_queue<Entry, std::vector<Entry>, std::greater<>> heap;
  for (std::size_t i = 0; i < parts.size(); ++i) heap.emplace(parts[i]->event, i);

  // Record{event = <bytes>}: tag of field 2 with wire type 2 (length-delimited),
  // the size of the event, the event.
  constexpr char kEventTag = (2 << 3) | 2;
  long events = 0;
  while (!heap.empty()) {
    const std::size_t i = heap.top().second;
    heap.pop();
    Part& part = *parts[i];
    const std::uint64_t size = part.bytes.size();
    WriteVarint(out, 1 + VarintSize(size) + size);
    out.put(kEventTag);
    WriteVarint(out, size);
    out.write(part.bytes.data(), static_cast<std::streamsize>(size));
    ++events;
    if (part.Next()) heap.emplace(part.event, i);
  }

  siplate::Record footer;
  footer.mutable_footer()->set_n_events(events);
  WriteRecord(out, footer);
  out.close();
  parts.clear();

  for (const auto& f : files) fs::remove(f);
  std::cout << "RecordFile: " << files.size() << " part(s) -> " << base << ".pb ("
            << events << " events)\n";
  return events;
}

}  // namespace RecordFile
