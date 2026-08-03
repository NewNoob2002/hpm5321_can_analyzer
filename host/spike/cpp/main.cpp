#include <array>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <fstream>
#include <iostream>
#include <cstdlib>
#include <string>

int main() {
    constexpr std::uint32_t frames = 1'000'000;
    const auto start = std::chrono::steady_clock::now();
    std::uint32_t start_sequence = 0;
    std::uint64_t checksum = 0xcbf29ce484222325ULL;
    std::uint32_t reconnects = 0;
    const char* state_path = std::getenv("SPIKE_STATE");
    const char* crash_value = std::getenv("SPIKE_CRASH_AT");
    const std::uint32_t crash_at = crash_value ? std::stoul(crash_value) : 0;
    if (state_path) {
        std::ifstream state(state_path);
        state >> start_sequence >> checksum >> reconnects;
    }
    for (std::uint32_t sequence = start_sequence; sequence < frames; ++sequence) {
        if (sequence != 0 && sequence % 10'000 == 0) {
            ++reconnects;
        }
        std::array<std::uint8_t, 16> frame{};
        std::memcpy(frame.data(), "HPM1", 4);
        const std::uint32_t id = 0x123;
        const std::uint32_t payload = sequence ^ 0xa5a55a5aU;
        std::memcpy(frame.data() + 4, &sequence, 4);
        std::memcpy(frame.data() + 8, &id, 4);
        std::memcpy(frame.data() + 12, &payload, 4);
        for (const auto byte : frame) {
            checksum ^= byte;
            checksum *= 0x100000001b3ULL;
        }
        if (crash_at != 0 && sequence + 1 == crash_at) {
            std::ofstream state(state_path);
            state << sequence + 1 << ' ' << checksum << ' ' << reconnects << '\n';
            return 75;
        }
    }
    if (state_path) { std::remove(state_path); }
    const auto elapsed = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    std::cout << "{\"candidate\":\"cpp-core\",\"frames\":" << frames
              << ",\"checksum\":\"" << std::hex << std::setw(16)
              << std::setfill('0') << checksum << std::dec
              << "\",\"reconnects\":" << reconnects
              << ",\"recovered\":" << reconnects
              << ",\"elapsed_ms\":" << std::fixed << std::setprecision(3)
              << elapsed * 1000.0 << ",\"frames_per_second\":"
              << std::setprecision(0) << (frames - start_sequence) / elapsed << "}\n";
}
