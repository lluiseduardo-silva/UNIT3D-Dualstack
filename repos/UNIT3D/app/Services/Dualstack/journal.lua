-- Todas as verificacoes antecedem a primeira mutacao. O payload financeiro e
-- opaco: uint64 permanece decimal, sem passar por numeros de ponto flutuante Lua.
if redis.call('HGET', KEYS[7], 'owner_id') ~= ARGV[1]
    or redis.call('HGET', KEYS[7], 'ready') ~= ARGV[2]
    or redis.call('GET', KEYS[8]) ~= ARGV[1] then return {'unavailable'} end
if redis.call('SISMEMBER', KEYS[9], ARGV[13]) == 1 or redis.call('SISMEMBER', KEYS[10], ARGV[14]) == 1 then return {'removed'} end
if (redis.call('GET', KEYS[1]) or '') ~= ARGV[3]
    or (redis.call('GET', KEYS[2]) or '') ~= ARGV[4]
    or (redis.call('GET', KEYS[3]) or '0') ~= ARGV[5] then return {'conflict'} end
for index, expected in pairs({[1]='string',[2]='string',[3]='string',[4]='zset',[5]='zset',[6]='stream'}) do
    local actual = redis.call('TYPE', KEYS[index]).ok
    if actual ~= 'none' and actual ~= expected then return {'invalid_storage_type'} end
end
if redis.call('XLEN', KEYS[6]) >= tonumber(ARGV[9]) then return {'backlog_full'} end

-- Se um erro de armazenamento interromper o script, ready permanece zero.
-- Recuperar/drenar o journal e recarregar SQL antes de liberar novos announces.
redis.call('HSET', KEYS[7], 'ready', '0')
local id = redis.call('XADD', KEYS[6], '*', 'payload', ARGV[8])
redis.call('SET', KEYS[1], ARGV[6])
redis.call('SET', KEYS[2], ARGV[7])
redis.call('INCR', KEYS[3])
if tonumber(ARGV[11]) > 0 then redis.call('ZADD', KEYS[4], ARGV[11], ARGV[10])
else redis.call('ZREM', KEYS[4], ARGV[10]) end
if tonumber(ARGV[12]) > 0 then redis.call('ZADD', KEYS[5], ARGV[12], ARGV[10])
else redis.call('ZREM', KEYS[5], ARGV[10]) end
redis.call('HSET', KEYS[7], 'ready', ARGV[2])
return {'accepted', id}
