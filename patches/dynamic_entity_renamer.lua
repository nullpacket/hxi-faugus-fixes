local registry = {}
local name_list = {}
local isWindowerv4 = windower ~= nil
local isAshitav4 = ashita ~= nil and ashita.events ~= nil

local is_on_retail = nil -- only used in Ashita v4
local ffi          = nil --

local zoneState =
{
    isZoning   = true,
    zoneId     = nil,
    pending0E  = {},
    pending0FF = nil,
    lastZone   = nil,
    zoneStable = false,
}

local struct = {}

if isAshitav4 then
    require('common')
    addon.name = 'dynamic_entity_renamer'
    addon.author = 'zach2good, TeoTwawki, atom0s'
    addon.version = '1.0.0.0'


    ffi = require("ffi")
    ffi.cdef("void* GetModuleHandleA(const char*)")

    is_on_retail = function()
        return ffi.C.GetModuleHandleA("polhook.dll") ~= nil
    end
elseif isWindowerv4 then
    _addon.name = 'dynamic_entity_renamer'
    _addon.author = 'zach2good, TeoTwawki, atom0s'
    _addon.version = '1.0.0.0'
    _addon.command = 'dynamic_entity_renamer'
    bit = require 'bit'
end

function struct.pack(format, ...)
    local stream = {}
    local vars = {...}
    local endianness = true

    for i = 1, format:len() do
        local opt = format:sub(i, i)

        if opt == '<' then
        endianness = true
        elseif opt == '>' then
        endianness = false
        elseif opt:find('[bBhHiIlL]') then
        local n = opt:find('[hH]') and 2 or opt:find('[iI]') and 4 or opt:find('[lL]') and 8 or 1
        local val = tonumber(table.remove(vars, 1))

        local bytes = {}
        for j = 1, n do
            table.insert(bytes, string.char(val % (2 ^ 8)))
            val = math.floor(val / (2 ^ 8))
        end

        if not endianness then
            table.insert(stream, string.reverse(table.concat(bytes)))
        else
            table.insert(stream, table.concat(bytes))
        end
        elseif opt:find('[fd]') then
        local val = tonumber(table.remove(vars, 1))
        local sign = 0

        if val < 0 then
            sign = 1
            val = -val
        end

        local mantissa, exponent = math.frexp(val)
        if val == 0 then
            mantissa = 0
            exponent = 0
        else
            mantissa = (mantissa * 2 - 1) * math.ldexp(0.5, (opt == 'd') and 53 or 24)
            exponent = exponent + ((opt == 'd') and 1022 or 126)
        end

        local bytes = {}
        if opt == 'd' then
            val = mantissa
            for i = 1, 6 do
            table.insert(bytes, string.char(math.floor(val) % (2 ^ 8)))
            val = math.floor(val / (2 ^ 8))
            end
        else
            table.insert(bytes, string.char(math.floor(mantissa) % (2 ^ 8)))
            val = math.floor(mantissa / (2 ^ 8))
            table.insert(bytes, string.char(math.floor(val) % (2 ^ 8)))
            val = math.floor(val / (2 ^ 8))
        end

        table.insert(bytes, string.char(math.floor(exponent * ((opt == 'd') and 16 or 128) + val) % (2 ^ 8)))
        val = math.floor((exponent * ((opt == 'd') and 16 or 128) + val) / (2 ^ 8))
        table.insert(bytes, string.char(math.floor(sign * 128 + val) % (2 ^ 8)))
        val = math.floor((sign * 128 + val) / (2 ^ 8))

        if not endianness then
            table.insert(stream, string.reverse(table.concat(bytes)))
        else
            table.insert(stream, table.concat(bytes))
        end
        elseif opt == 's' then
        table.insert(stream, tostring(table.remove(vars, 1)))
        table.insert(stream, string.char(0))
        elseif opt == 'c' then
        local n = format:sub(i + 1):match('%d+')
        local str = tostring(table.remove(vars, 1))
        local len = tonumber(n)
        if len <= 0 then
            len = str:len()
        end
        if len - str:len() > 0 then
            str = str .. string.rep(' ', len - str:len())
        end
        table.insert(stream, str:sub(1, len))
        i = i + n:len()
        end
    end

    return table.concat(stream)
end

function struct.unpack(format, stream, pos)
  local vars = {}
  local iterator = pos or 1
  local endianness = true

  for i = 1, format:len() do
    local opt = format:sub(i, i)

    if opt == '<' then
      endianness = true
    elseif opt == '>' then
      endianness = false
    elseif opt:find('[bBhHiIlL]') then
      local n = opt:find('[hH]') and 2 or opt:find('[iI]') and 4 or opt:find('[lL]') and 8 or 1
      local signed = opt:lower() == opt

      local val = 0
      for j = 1, n do
        local byte = string.byte(stream:sub(iterator, iterator))
        if endianness then
          val = val + byte * (2 ^ ((j - 1) * 8))
        else
          val = val + byte * (2 ^ ((n - j) * 8))
        end
        iterator = iterator + 1
      end

      if signed and val >= 2 ^ (n * 8 - 1) then
        val = val - 2 ^ (n * 8)
      end

      table.insert(vars, math.floor(val))
    elseif opt:find('[fd]') then
      local n = (opt == 'd') and 8 or 4
      local x = stream:sub(iterator, iterator + n - 1)
      iterator = iterator + n

      if not endianness then
        x = string.reverse(x)
      end

      local sign = 1
      local mantissa = string.byte(x, (opt == 'd') and 7 or 3) % ((opt == 'd') and 16 or 128)
      for i = n - 2, 1, -1 do
        mantissa = mantissa * (2 ^ 8) + string.byte(x, i)
      end

      if string.byte(x, n) > 127 then
        sign = -1
      end

      local exponent = (string.byte(x, n) % 128) * ((opt == 'd') and 16 or 2) + math.floor(string.byte(x, n - 1) / ((opt == 'd') and 16 or 128))
      if exponent == 0 then
        table.insert(vars, 0.0)
      else
        mantissa = (math.ldexp(mantissa, (opt == 'd') and -52 or -23) + 1) * sign
        table.insert(vars, math.ldexp(mantissa, exponent - ((opt == 'd') and 1023 or 127)))
      end
    elseif opt == 's' then
      local bytes = {}
      for j = iterator, stream:len() do
        if stream:sub(j,j) == string.char(0) or  stream:sub(j) == '' then
          break
        end

        table.insert(bytes, stream:sub(j, j))
      end

      local str = table.concat(bytes)
      iterator = iterator + str:len() + 1
      table.insert(vars, str)
    elseif opt == 'c' then
      local n = format:sub(i + 1):match('%d+')
      local len = tonumber(n)
      if len <= 0 then
        len = table.remove(vars)
      end

      table.insert(vars, stream:sub(iterator, iterator + len - 1))
      iterator = iterator + len
      i = i + n:len()
    end
  end

  return unpack(vars)
end

local function split(str, ch)
    local outTable = {}
    for word in string.gmatch(str, '([^' .. ch .. ']+)') do
        table.insert(outTable, word)
    end
    return outTable
end

local function setMobName(id, name, zoneId)
    if name_list[zoneId] then
        local new_name = name_list[zoneId][name.original_name]

        if new_name then
            if isWindowerv4 then
                windower.set_mob_name(id + 0x100, new_name)
                -- 0x100 offset may change if pets + trusts + dynamic entities all share the same space
            elseif isAshitav4 then
                local targid = bit.band(id, 0x0FFF)
                local entity = AshitaCore:GetMemoryManager():GetEntity()
                -- Defense in depth against Wine-side AV storm (Windows tolerates the
                -- same accesses via LFH; Wine's strict memory layout faults). Each
                -- caught AV grows the unwind function table, slowly leaking 32-bit VA.
                -- Skip if entity slot is empty/despawned.
                if entity:GetActorPointer(targid) == 0 then
                    return
                end
                -- Skip if entity isn't fully spawned. Catches mid-initialization
                -- states (BC mob spawn, busy-zone NPC stream-in) that pass the
                -- ActorPointer check but have inconsistent inner state.
                if entity:GetSpawnFlags(targid) == 0 then
                    return
                end
                -- Skip if current name already matches; avoids redundant writes.
                if entity:GetName(targid) == new_name then
                    return
                end
                -- Wrap in pcall as last-resort guard. Any error becomes a swallowed
                -- Lua error instead of a caught C++ exception that retries every frame.
                pcall(function() entity:SetName(targid, new_name) end)
            end
        end
    end
end

-- Throttle render() to ~10 Hz instead of 60+. Names do not need 60 Hz refresh;
-- this cuts per-frame iteration cost (and residual AV exposure) with no visible
-- difference. Upstream calls render() from d3d_beginscene every frame.
local last_render = 0
local render_interval = 0.1  -- seconds

local function render()
    local now = os.clock()
    if now - last_render < render_interval then
        return
    end
    last_render = now

    if registry[currentZone] then
        for k, v in pairs(registry[currentZone]) do
            if k and v then
                setMobName(k, v, currentZone)
            end
        end
    end
end

local function askForList()
    if isWindowerv4 then
        windower.packets.inject_outgoing(0x01, struct.pack("c4", { 0x01, 0x04, 0x00, 0x00 }))
    elseif isAshitav4 and is_on_retail() == false then
        AshitaCore:GetPacketManager():AddOutgoingPacket(0x01, { 0x01, 0x04, 0x00, 0x00 })
    end
end

local function handleList(id, data)
    if id ~= 0x1FF then
        return
    end

    local parts = split(data, '|')
    local zoneId = tonumber(parts[1])

    if not zoneId then
        return
    end

    currentZone = zoneId

    if not name_list[zoneId] then
        name_list[zoneId] = {}
    end

    registry = registry or {}
    registry[zoneId] = registry[zoneId] or {}

    for i = 2, #parts do
        local entry = parts[i]
        if entry and entry ~= '' then
            local kv = split(entry, ':')
            if kv[1] and kv[2] then
                name_list[zoneId][kv[1]] = kv[2]
            end
        end
    end

    render()
end

local function register_dynamic_entity(data, zoneId)
    local name   = struct.unpack('s', data, 0x34 + 1)
    local targid = struct.unpack('H', data, 0x08 + 1)
    local flags  = struct.unpack('B', data, 0x0A + 1)
    local nameflag = 0x08

    -- check if flags contain rename flag and is in "dynamic entity" range
    if bit.band(flags, nameflag) ~= 0 and targid >= 0x700 then
        local fullid = 0x1000000 + bit.lshift(zoneId, 12) + targid

        if registry[zoneId] == nil then
            registry[zoneId] = {}
        end

        registry[zoneId][fullid] = {original_name = name:sub(1, -2)}
    end
end

if isWindowerv4 then
    windower.register_event('load', function()
        askForList()
    end)
    windower.register_event('zone change', function()
        askForList()
    end)
    windower.register_event('incoming chunk', function(id, data)
        if id == 0x0E then
            register_dynamic_entity(data)
        elseif id == 0x1FF then
            handleList(id, data:sub(5))
        end
    end)
    windower.register_event("prerender", function()
        render()
    end)
end -- isWindowerv4

if isAshitav4 then
    ashita.events.register('load', 'load_cb', function()
        askForList()
    end)
    ashita.events.register('packet_out', 'packet_out_cb', function(e)
        if e.id == 0x0A then
            zoneState.isZoning   = true
            zoneState.zoneId     = nil
            zoneState.pending0E  = {}
            zoneState.pending0FF = nil
            zoneState.zoneStable = false
            name_list            = {}
        elseif e.id == 0x011 then
            askForList()
        end
    end)
    ashita.events.register('packet_in', 'packet_in_cb', function(e)
        if e.id == 0x0E then
            if not zoneState.zoneStable or not zoneState.currentZone then
                zoneState.pending0E[#zoneState.pending0E + 1] = e.data
                return
            end

            register_dynamic_entity(e.data, zoneState.currentZone)
        elseif e.id == 0x1FF then
            zoneState.pending0FF = e.data:sub(5)
        end
    end)
    ashita.events.register('d3d_beginscene', 'beginscene_cb', function()
        local player = AshitaCore:GetMemoryManager():GetPlayer()
        local zoneId = AshitaCore:GetMemoryManager():GetParty():GetMemberZone(0)

        if not player then
            return
        end

        if zoneState.lastZone ~= zoneId then
            zoneState.isZoning = true
            zoneState.lastZone = zoneId
            return
        end

        if zoneState.isZoning and zoneId and zoneId ~= 0 and not player.isZoning then
            zoneState.currentZone = zoneId
            zoneState.isZoning    = false
            zoneState.zoneStable  = true

            if zoneState.pending0FF then
                handleList(0x1FF, zoneState.pending0FF)
                zoneState.pending0FF = nil
            end

            for i = 1, #zoneState.pending0E do
                register_dynamic_entity(zoneState.pending0E[i], zoneState.currentZone)
            end

            zoneState.pending0E = {}
        end

        render()
    end)
end -- isAshitav4