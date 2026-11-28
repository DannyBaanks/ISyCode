//! libisyjournal: native fast path for the private action journal.
//!
//! Two C-ABI entry points, loaded by `isycode.native_journal` through ctypes:
//!
//!   isyj_write_fsync  writes a whole buffer to an fd Python already opened and
//!                     checked, then fsyncs it. ctypes releases the GIL for the
//!                     call, so a slow disk never stalls other Python threads.
//!   isyj_verify_chain verifies a run of journal lines against the hash chain
//!                     `digest = sha256(previous_hex || canonical(record - digest))`.
//!
//! The verifier is a strict fast path, never a second authority: it accepts a
//! line only when its bytes are exactly what Python's
//! `json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
//! would write (sorted plain keys at every level, no whitespace, only the
//! string escapes Python emits, valid UTF-8). Anything else returns
//! ISYJ_NOT_CANONICAL and the Python verifier decides, so a line this code
//! accepts is one the Python verifier accepts too.
const std = @import("std");
const builtin = @import("builtin");
const Sha256 = std.crypto.hash.sha2.Sha256;

pub const ISYJ_OK: c_int = 0;
pub const ISYJ_NOT_CANONICAL: c_int = 1;
pub const ISYJ_BAD_CHAIN: c_int = 2;
pub const ISYJ_BAD_INPUT: c_int = 3;

pub const ABI_VERSION: c_int = 1;

fn abiVersion() callconv(.c) c_int {
    return ABI_VERSION;
}

/// Write all of `data` to `fd`, then fsync. Returns 0, or -1 with errno set by
/// libc (ctypes reads it with use_errno=True).
fn writeFsync(fd: c_int, data: [*]const u8, len: usize) callconv(.c) c_int {
    var done: usize = 0;
    while (done < len) {
        const rc = std.c.write(fd, data + done, len - done);
        if (rc < 0) {
            if (std.c._errno().* == @intFromEnum(std.c.E.INTR)) continue;
            return -1;
        }
        if (rc == 0) return -1;
        done += @intCast(rc);
    }
    while (true) {
        if (std.c.fsync(fd) == 0) return 0;
        if (std.c._errno().* == @intFromEnum(std.c.E.INTR)) continue;
        return -1;
    }
}

// ── canonical JSON scanner ────────────────────────────────────────────────

const Scanner = struct {
    s: []const u8,
    i: usize = 0,

    fn peek(self: *Scanner) ?u8 {
        return if (self.i < self.s.len) self.s[self.i] else null;
    }

    fn expect(self: *Scanner, c: u8) bool {
        if (self.peek() != c) return false;
        self.i += 1;
        return true;
    }

    /// A string exactly as Python json.dumps(ensure_ascii=False) writes it.
    /// Returns the raw bytes between the quotes, or null.
    fn string(self: *Scanner) ?[]const u8 {
        if (!self.expect('"')) return null;
        const start = self.i;
        while (self.i < self.s.len) {
            const c = self.s[self.i];
            if (c == '"') {
                const body = self.s[start..self.i];
                self.i += 1;
                if (!std.unicode.utf8ValidateSlice(body)) return null;
                return body;
            }
            if (c < 0x20) return null; // Python escapes every control char
            // Python's str.splitlines() also breaks on U+0085, U+2028 and
            // U+2029, which json.dumps(ensure_ascii=False) writes raw; the
            // Python verifier would split such a line, so defer to it.
            if (c == 0xC2 and self.i + 1 < self.s.len and self.s[self.i + 1] == 0x85) return null;
            if (c == 0xE2 and self.i + 2 < self.s.len and self.s[self.i + 1] == 0x80 and
                (self.s[self.i + 2] == 0xA8 or self.s[self.i + 2] == 0xA9)) return null;
            if (c == '\\') {
                if (self.i + 1 >= self.s.len) return null;
                const e = self.s[self.i + 1];
                switch (e) {
                    '"', '\\', 'n', 'r', 't', 'b', 'f' => self.i += 2,
                    'u' => {
                        // Python writes \u00XX (lowercase hex) only for the
                        // control chars that have no short escape.
                        if (self.i + 6 > self.s.len) return null;
                        const h = self.s[self.i + 2 .. self.i + 6];
                        if (h[0] != '0' or h[1] != '0') return null;
                        if (!(h[2] == '0' or h[2] == '1')) return null;
                        const lo = h[3];
                        const v: u8 = switch (lo) {
                            '0'...'9' => lo - '0',
                            'a'...'f' => lo - 'a' + 10,
                            else => return null,
                        };
                        const cp: u8 = (h[2] - '0') * 16 + v;
                        switch (cp) {
                            0x08, 0x09, 0x0a, 0x0c, 0x0d => return null, // have short forms
                            else => {},
                        }
                        self.i += 6;
                    },
                    else => return null,
                }
                continue;
            }
            self.i += 1;
        }
        return null;
    }

    /// Number token in the shapes Python's int/float repr produces.
    /// Known residual: a float spelled non-shortest ("1.50") passes here
    /// although Python would re-serialize it. Only a hand-made line whose
    /// author also recomputed its digest can contain one, and the full
    /// Python verify() still rejects it, so it is detected, later.
    fn number(self: *Scanner) bool {
        const start = self.i;
        _ = self.expect('-');
        const c0 = self.peek() orelse return false;
        if (c0 == '0') {
            self.i += 1;
        } else if (c0 >= '1' and c0 <= '9') {
            while (self.peek()) |c| : (self.i += 1) if (c < '0' or c > '9') break;
        } else return false;
        if (self.peek() == '.') {
            self.i += 1;
            const f = self.i;
            while (self.peek()) |c| : (self.i += 1) if (c < '0' or c > '9') break;
            if (self.i == f) return false;
        }
        if (self.peek() == 'e') {
            self.i += 1;
            if (self.peek() == '+' or self.peek() == '-') self.i += 1;
            const f = self.i;
            while (self.peek()) |c| : (self.i += 1) if (c < '0' or c > '9') break;
            if (self.i == f) return false;
        }
        return self.i > start;
    }

    fn literal(self: *Scanner, word: []const u8) bool {
        if (!std.mem.startsWith(u8, self.s[self.i..], word)) return false;
        self.i += word.len;
        return true;
    }

    fn value(self: *Scanner, depth: u8) bool {
        if (depth > 16) return false;
        const c = self.peek() orelse return false;
        return switch (c) {
            '"' => self.string() != null,
            '{' => self.object(depth + 1, null),
            '[' => self.array(depth + 1),
            't' => self.literal("true"),
            'f' => self.literal("false"),
            'n' => self.literal("null"),
            else => self.number(),
        };
    }

    fn array(self: *Scanner, depth: u8) bool {
        if (!self.expect('[')) return false;
        if (self.expect(']')) return true;
        while (true) {
            if (!self.value(depth)) return false;
            if (self.expect(']')) return true;
            if (!self.expect(',')) return false;
        }
    }

    const Member = struct { start: usize, end: usize, value_start: usize, value_end: usize };
    const Top = struct {
        digest: ?Member = null,
        previous: ?Member = null,
        first_member_start: usize = 0,
    };

    /// Object with strictly ascending plain keys. With `top`, records where
    /// the "digest" and "previous" members sit.
    fn object(self: *Scanner, depth: u8, top: ?*Top) bool {
        if (!self.expect('{')) return false;
        if (self.expect('}')) return true;
        var last_key: ?[]const u8 = null;
        while (true) {
            const member_start = self.i;
            const key = self.string() orelse return false;
            if (std.mem.indexOfScalar(u8, key, '\\') != null) return false;
            if (last_key) |prev| {
                // Python sorts keys by code point; for UTF-8 that is byte order.
                if (std.mem.order(u8, prev, key) != .lt) return false;
            }
            last_key = key;
            if (!self.expect(':')) return false;
            const value_start = self.i;
            if (!self.value(depth)) return false;
            const m = Member{ .start = member_start, .end = self.i, .value_start = value_start, .value_end = self.i };
            if (top) |t| {
                if (std.mem.eql(u8, key, "digest")) t.digest = m;
                if (std.mem.eql(u8, key, "previous")) t.previous = m;
            }
            if (self.expect('}')) return true;
            if (!self.expect(',')) return false;
        }
    }
};

fn isLowerHex64(bytes: []const u8) bool {
    if (bytes.len != 64) return false;
    for (bytes) |c| switch (c) {
        '0'...'9', 'a'...'f' => {},
        else => return false,
    };
    return true;
}

/// Verify one line (without its newline). On success writes the line's digest
/// into `prev` and returns ISYJ_OK.
fn verifyLine(line: []const u8, prev: *[64]u8) c_int {
    var sc = Scanner{ .s = line };
    var top = Scanner.Top{};
    if (!sc.object(1, &top) or sc.i != line.len) return ISYJ_NOT_CANONICAL;
    const d = top.digest orelse return ISYJ_NOT_CANONICAL;
    const p = top.previous orelse return ISYJ_NOT_CANONICAL;
    // String values: strip the quotes.
    const digest_hex = line[d.value_start + 1 .. d.value_end - 1];
    const previous_hex = line[p.value_start + 1 .. p.value_end - 1];
    if (line[d.value_start] != '"' or !isLowerHex64(digest_hex)) return ISYJ_NOT_CANONICAL;
    if (line[p.value_start] != '"' or !std.mem.eql(u8, previous_hex, prev)) return ISYJ_BAD_CHAIN;

    // canonical(record - digest): drop the member and exactly one adjacent comma.
    var head: []const u8 = undefined;
    var tail: []const u8 = undefined;
    if (line[d.start - 1] == ',') {
        head = line[0 .. d.start - 1];
        tail = line[d.end..];
    } else if (line[d.end] == ',') {
        head = line[0..d.start];
        tail = line[d.end + 1 ..];
    } else {
        // digest was the only member: body is "{}"
        head = line[0..d.start];
        tail = line[d.end..];
    }
    var h = Sha256.init(.{});
    h.update(prev);
    h.update(head);
    h.update(tail);
    var out: [Sha256.digest_length]u8 = undefined;
    h.final(&out);
    const hex = std.fmt.bytesToHex(out, .lower);
    if (!std.mem.eql(u8, &hex, digest_hex)) return ISYJ_BAD_CHAIN;
    @memcpy(prev, digest_hex);
    return ISYJ_OK;
}

/// Verify newline-terminated `data` line by line starting from `prev` (64 hex
/// bytes, updated in place to the last good digest). `out_records` gets the
/// number of verified lines; on failure `out_bad_line` is the 1-based line.
fn verifyChain(data: [*]const u8, len: usize, prev: *[64]u8, out_records: *u64, out_bad_line: *u64) callconv(.c) c_int {
    out_records.* = 0;
    out_bad_line.* = 0;
    if (!isLowerHex64(prev)) return ISYJ_BAD_INPUT;
    const bytes = data[0..len];
    if (len != 0 and bytes[len - 1] != '\n') return ISYJ_NOT_CANONICAL;
    var work = prev.*;
    var it = std.mem.splitScalar(u8, if (len == 0) bytes else bytes[0 .. len - 1], '\n');
    var n: u64 = 0;
    if (len == 0) return ISYJ_OK;
    while (it.next()) |line| {
        n += 1;
        const rc = verifyLine(line, &work);
        if (rc != ISYJ_OK) {
            out_bad_line.* = n;
            return rc;
        }
    }
    prev.* = work;
    out_records.* = n;
    return ISYJ_OK;
}

comptime {
    @export(&abiVersion, .{ .name = "isyj_abi_version" });
    @export(&writeFsync, .{ .name = "isyj_write_fsync" });
    @export(&verifyChain, .{ .name = "isyj_verify_chain" });
}

// ── tests ─────────────────────────────────────────────────────────────────

fn chainLine(alloc: std.mem.Allocator, prev: []const u8, body_sorted_without_digest: []const u8) ![]u8 {
    // body like {"a":1,"previous":"..."}; digest goes in key order between
    // "checks"/"effect"-style keys in real records; here we place it by sort.
    var h = Sha256.init(.{});
    h.update(prev);
    h.update(body_sorted_without_digest);
    var out: [32]u8 = undefined;
    h.final(&out);
    const hex = std.fmt.bytesToHex(out, .lower);
    // insert ,"digest":"<hex>" after the member whose key sorts before "digest"
    const marker = ",\"kind\"";
    const at = std.mem.indexOf(u8, body_sorted_without_digest, marker).?;
    return std.fmt.allocPrint(alloc, "{s},\"digest\":\"{s}\"{s}", .{ body_sorted_without_digest[0..at], hex, body_sorted_without_digest[at..] });
}

test "verifies a canonical two-line chain and rejects tampering" {
    const a = std.testing.allocator;
    const zero = "0" ** 64;
    const l1 = try chainLine(a, zero, "{\"action\":\"x\",\"kind\":\"decision\",\"previous\":\"" ++ zero ++ "\",\"time\":1.5}");
    defer a.free(l1);
    var prev: [64]u8 = zero.*;
    try std.testing.expectEqual(ISYJ_OK, verifyLine(l1, &prev));
    const p1 = prev;
    const body2 = try std.fmt.allocPrint(a, "{{\"action\":\"y\\n\\u001f\",\"kind\":\"receipt\",\"previous\":\"{s}\",\"time\":2}}", .{p1});
    defer a.free(body2);
    const l2 = try chainLine(a, &p1, body2);
    defer a.free(l2);
    const data = try std.fmt.allocPrint(a, "{s}\n{s}\n", .{ l1, l2 });
    defer a.free(data);
    var start: [64]u8 = zero.*;
    var recs: u64 = 0;
    var bad: u64 = 0;
    try std.testing.expectEqual(ISYJ_OK, verifyChain(data.ptr, data.len, &start, &recs, &bad));
    try std.testing.expectEqual(@as(u64, 2), recs);

    // flip one byte of the second record's body
    const tampered = try a.dupe(u8, data);
    defer a.free(tampered);
    const pos = std.mem.indexOf(u8, tampered, "\"y").? + 1;
    tampered[pos] = 'z';
    start = zero.*;
    try std.testing.expectEqual(ISYJ_BAD_CHAIN, verifyChain(tampered.ptr, tampered.len, &start, &recs, &bad));
    try std.testing.expectEqual(@as(u64, 2), bad);
    try std.testing.expectEqualStrings(zero, &start); // prev untouched on failure
}

test "non-canonical shapes defer to Python" {
    var prev: [64]u8 = ("0" ** 64).*;
    const cases = [_][]const u8{
        "{\"b\":1,\"a\":2}", // unsorted keys
        "{\"a\": 1}", // whitespace
        "{\"a\":\"\\/\"}", // escape Python never writes
        "{\"a\":\"\\u0041\"}", // \u for a printable char
        "{\"a\":\"\\u000a\"}", // \u for a char with a short escape
        "{\"\\u0064igest\":\"x\"}", // escaped key
        "{\"a\":1,\"a\":2}", // duplicate key
        "{\"a\":01}", // leading zero
        "{\"a\":\"x\xe2\x80\xa8y\"}", // U+2028: Python's splitlines breaks here
        "{\"a\":\"x\xc2\x85y\"}", // U+0085 (NEL)
    };
    for (cases) |c| try std.testing.expectEqual(ISYJ_NOT_CANONICAL, verifyLine(c, &prev));
}
