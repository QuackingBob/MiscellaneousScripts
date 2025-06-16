-- Node Network Protocol Descriptors
-- These descriptors define the structure of the UDP packets for position and graph data

-- Position Packet Descriptor
local position_packet = {
    name = "PositionPacket",
    description = "Node position announcement packet",
    port = 12345,
    size = 10, -- 2 + 4 + 4 bytes
    fields = {
        {
            name = "node_id",
            type = "uint16",
            offset = 0,
            size = 2,
            description = "Unique identifier for the node",
            endian = "little"
        },
        {
            name = "x",
            type = "float32",
            offset = 2,
            size = 4,
            description = "X coordinate position",
            endian = "little"
        },
        {
            name = "y",
            type = "float32",
            offset = 6,
            size = 4,
            description = "Y coordinate position",
            endian = "little"
        }
    }
}

-- Graph Edge Descriptor (sub-structure)
local graph_edge = {
    name = "GraphEdge",
    description = "Individual edge in a graph",
    size = 6, -- 2 + 2 + 2 bytes
    fields = {
        {
            name = "source_id",
            type = "uint16",
            offset = 0,
            size = 2,
            description = "Source node ID for this edge",
            endian = "little"
        },
        {
            name = "target_id",
            type = "uint16",
            offset = 2,
            size = 2,
            description = "Target node ID for this edge",
            endian = "little"
        },
        {
            name = "strength",
            type = "uint16",
            offset = 4,
            size = 2,
            description = "Connection strength value",
            endian = "little"
        }
    }
}

-- Graph Packet Descriptor
local graph_packet = {
    name = "GraphPacket",
    description = "Node graph announcement packet",
    port = 12346,
    max_size = 304, -- 2 + 2 + (50 * 6) bytes
    fields = {
        {
            name = "sender_id",
            type = "uint16",
            offset = 0,
            size = 2,
            description = "ID of the node sending this graph",
            endian = "little"
        },
        {
            name = "edge_count",
            type = "uint16",
            offset = 2,
            size = 2,
            description = "Number of edges in this packet",
            endian = "little",
            max_value = 50
        },
        {
            name = "edges",
            type = "array",
            offset = 4,
            element_type = "GraphEdge",
            element_size = 6,
            count_field = "edge_count",
            max_count = 50,
            description = "Array of graph edges"
        }
    }
}

-- Protocol Suite Descriptor
local node_network_protocol = {
    name = "NodeNetworkProtocol",
    version = "1.0",
    description = "UDP-based node position and graph broadcasting protocol",
    packets = {
        position = position_packet,
        graph = graph_packet
    }
}

-- Utility functions for parsing

-- Parse position packet from binary data
function parse_position_packet(data)
    if #data < 10 then
        return nil, "Insufficient data for position packet"
    end
    
    local node_id = string.unpack("<I2", data, 1)
    local x = string.unpack("<f", data, 3)
    local y = string.unpack("<f", data, 7)
    
    return {
        node_id = node_id,
        x = x,
        y = y,
        packet_type = "position"
    }
end

-- Parse graph packet from binary data
function parse_graph_packet(data)
    if #data < 4 then
        return nil, "Insufficient data for graph packet header"
    end
    
    local sender_id = string.unpack("<I2", data, 1)
    local edge_count = string.unpack("<I2", data, 3)
    
    if edge_count > 50 then
        return nil, "Invalid edge count: " .. edge_count
    end
    
    local required_size = 4 + (edge_count * 6)
    if #data < required_size then
        return nil, "Insufficient data for graph packet edges"
    end
    
    local edges = {}
    local offset = 5
    
    for i = 1, edge_count do
        local source_id = string.unpack("<I2", data, offset)
        local target_id = string.unpack("<I2", data, offset + 2)
        local strength = string.unpack("<I2", data, offset + 4)
        
        table.insert(edges, {
            source_id = source_id,
            target_id = target_id,
            strength = strength
        })
        
        offset = offset + 6
    end
    
    return {
        sender_id = sender_id,
        edge_count = edge_count,
        edges = edges,
        packet_type = "graph"
    }
end

-- Packet identification function
function identify_packet(data, source_port)
    if source_port == 12345 then
        return parse_position_packet(data)
    elseif source_port == 12346 then
        return parse_graph_packet(data)
    else
        return nil, "Unknown packet type for port " .. source_port
    end
end

-- Validation functions
function validate_position_packet(packet)
    if not packet.node_id or packet.node_id < 1 or packet.node_id > 65535 then
        return false, "Invalid node_id"
    end
    
    if not packet.x or not packet.y then
        return false, "Missing coordinates"
    end
    
    if packet.x < 0 or packet.x > 1000 or packet.y < 0 or packet.y > 1000 then
        return false, "Coordinates out of valid range (0-1000)"
    end
    
    return true
end

function validate_graph_packet(packet)
    if not packet.sender_id or packet.sender_id < 1 or packet.sender_id > 65535 then
        return false, "Invalid sender_id"
    end
    
    if not packet.edge_count or packet.edge_count < 0 or packet.edge_count > 50 then
        return false, "Invalid edge_count"
    end
    
    if #packet.edges ~= packet.edge_count then
        return false, "Edge count mismatch"
    end
    
    for i, edge in ipairs(packet.edges) do
        if not edge.source_id or not edge.target_id or not edge.strength then
            return false, "Invalid edge at index " .. i
        end
        
        if edge.source_id == edge.target_id then
            return false, "Self-loop detected at index " .. i
        end
    end
    
    return true
end

-- Pretty print functions
function print_position_packet(packet)
    print(string.format("Position Packet - Node %d: (%.2f, %.2f)", 
          packet.node_id, packet.x, packet.y))
end

function print_graph_packet(packet)
    print(string.format("Graph Packet - Sender %d: %d edges", 
          packet.sender_id, packet.edge_count))
    
    for i, edge in ipairs(packet.edges) do
        print(string.format("  Edge %d: %d -> %d (strength: %d)", 
              i, edge.source_id, edge.target_id, edge.strength))
    end
end

-- Export the descriptors and functions
return {
    protocol = node_network_protocol,
    position_packet = position_packet,
    graph_packet = graph_packet,
    graph_edge = graph_edge,
    
    -- Parser functions
    parse_position_packet = parse_position_packet,
    parse_graph_packet = parse_graph_packet,
    identify_packet = identify_packet,
    
    -- Validation functions
    validate_position_packet = validate_position_packet,
    validate_graph_packet = validate_graph_packet,
    
    -- Utility functions
    print_position_packet = print_position_packet,
    print_graph_packet = print_graph_packet
}