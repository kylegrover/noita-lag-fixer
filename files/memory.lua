-- Process memory access for files/fixes.lua through the FFI of Noita's LuaJIT (unsafe mods only).
-- Errors at load if the FFI isn't available.
local ffi = require("ffi")

-- pcall each declaration: another mod in the same Lua state may have declared it already.
for _, declaration in ipairs({
    "void* __stdcall GetModuleHandleA(const char* name);",
    "void* __stdcall VirtualAlloc(void* address, size_t size, uint32_t type, uint32_t protect);",
    "int __stdcall VirtualProtect(void* address, size_t size, uint32_t protect, uint32_t* old);",
    "void* __stdcall GetCurrentProcess(void);",
    "int __stdcall FlushInstructionCache(void* process, const void* address, size_t size);",
    "uint32_t __stdcall GetEnvironmentVariableA(const char* name, char* buffer, uint32_t size);",
    "int __stdcall SetEnvironmentVariableA(const char* name, const char* value);",
}) do
    pcall(ffi.cdef, declaration)
end

local C = ffi.C
local MEM_COMMIT_RESERVE, PAGE_READWRITE = 0x3000, 0x04
local PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE = 0x20, 0x40
-- Process-wide, so a later Lua state (new game) finds the caves this process already has.
local MARKER = "NOITA_LAG_FIXER_CAVES"

local function address(pointer)
    return tonumber(ffi.cast("uintptr_t", pointer))
end

local function protect(va, n, protection)
    local old = ffi.new("uint32_t[1]")
    if C.VirtualProtect(ffi.cast("void*", va), n, protection, old) == 0 then
        error(string.format("VirtualProtect failed at %#x", va))
    end
    return old[0]
end

local memory = {}

function memory.image_base()
    return address(C.GetModuleHandleA(nil))
end

function memory.read(va, n)
    return ffi.string(ffi.cast("const char*", va), n)
end

function memory.write(va, bytes)
    local old = protect(va, #bytes, PAGE_EXECUTE_READWRITE)
    ffi.copy(ffi.cast("void*", va), bytes, #bytes)
    protect(va, #bytes, old)
    C.FlushInstructionCache(C.GetCurrentProcess(), ffi.cast("void*", va), #bytes)
end

function memory.alloc(code_bytes, data_bytes)
    local code = C.VirtualAlloc(nil, code_bytes, MEM_COMMIT_RESERVE, PAGE_READWRITE)
    local data = C.VirtualAlloc(nil, data_bytes, MEM_COMMIT_RESERVE, PAGE_READWRITE)
    if code == nil or data == nil then return nil, "VirtualAlloc failed" end
    return address(code), address(data)
end

function memory.seal(va, n)
    protect(va, n, PAGE_EXECUTE_READ)
    C.FlushInstructionCache(C.GetCurrentProcess(), ffi.cast("void*", va), n)
end

function memory.get_marker()
    local buffer = ffi.new("char[64]")
    local n = C.GetEnvironmentVariableA(MARKER, buffer, 64)
    if n == 0 or n >= 64 then return nil end
    return ffi.string(buffer, n)
end

function memory.set_marker(value)
    C.SetEnvironmentVariableA(MARKER, value)
end

return memory
