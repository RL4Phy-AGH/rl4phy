#ifndef RECORD_FILE_HH
#define RECORD_FILE_HH

#include <cstdint>
#include <fstream>
#include <string>

namespace siplate {
class Record;
}

// Writing <base>.pb, the delimited stream of siplate::Record messages described
// in proto/siplate.proto.
//
// Each thread (the only one in sequential mode) first writes its events to a
// part file, <base>_part<id>.bin, as frames of
//   [uint32 event_id][uint32 size][serialized siplate::Event]
// (little endian). At the end of the run Merge() writes the header, the events
// of all parts ordered by event ID and the footer to <base>.pb, and removes the
// parts. The event bytes are copied, not parsed: an Event of `size` bytes is
// wrapped as Record field 2 by prefixing its tag and size.
namespace RecordFile {

std::string PartPath(const std::string& base, int threadID);

// Removes part files of <base> left over from earlier, interrupted runs.
void RemoveParts(const std::string& base);

void WriteEventFrame(std::ofstream& out, std::int32_t eventID,
                     const std::string& eventBytes);

// Writes <base>.pb from the header and the part files, then removes the parts.
// Streams through the parts (k-way merge on event ID), so memory does not grow
// with the file size. Returns the number of events written.
long Merge(const std::string& base, const siplate::Record& header);

}  // namespace RecordFile

#endif
