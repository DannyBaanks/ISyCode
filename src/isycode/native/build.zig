// Builds libisyjournal (see isyjournal.zig). Optional: ISyCode runs the
// same journal in pure Python when the library is absent.
//
//   cd src/isycode/native && zig build -Doptimize=ReleaseSafe   # -> zig-out/lib/
//   zig build test
//
// `python -m isycode.native_journal build` runs this and copies the library
// next to this file, where the loader looks for it.
const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const mod = b.createModule(.{
        .root_source_file = b.path("isyjournal.zig"),
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .strip = optimize != .Debug,
    });
    const lib = b.addLibrary(.{ .linkage = .dynamic, .name = "isyjournal", .root_module = mod });
    b.installArtifact(lib);

    const tests = b.addTest(.{ .root_module = mod });
    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run libisyjournal unit tests");
    test_step.dependOn(&run_tests.step);
}
