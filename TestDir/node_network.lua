-- Node Network Protocol Wireshark Dissector
-- Save this file as: node_network.lua
-- Place it in Wireshark's plugins directory or load via Wireshark menu

-- Create the protocol
local node_network_proto = Proto("NodeNetwork", "Node Network Protocol")

-- Define protocol fields
local f = node_network_proto.fields

-- Position packet fields
f.pos_node_id = ProtoField.uint16("nodenet.pos.node_id", "Node ID", base.DEC)
f.pos_x = ProtoField.float("nodenet.pos.x", "X Coordinate")
f.pos_y = ProtoField.float("nodenet.pos.y", "Y Coordinate")

-- Graph packet fields
f.graph_sender_id = ProtoField.uint16("nodenet.graph.sender_id", "Sender ID", base.DEC)
f.graph_edge_count = ProtoField.uint16("nodenet.graph.edge_count", "Edge Count", base.DEC)

-- Graph edge fields
f.edge_source = ProtoField.uint16("nodenet.edge.source", "Source Node", base.DEC)
f.edge_target = ProtoField.uint16("nodenet.edge.target", "Target Node", base.DEC)
f.edge_strength = ProtoField.uint16("nodenet.edge.strength", "Strength", base.DEC)

-- Create expert info fields for warnings/errors
local ef = node_network_proto.experts
ef.invalid_length = ProtoExpert.new("nodenet.invalid_length", "Invalid packet length", 
                                   expert.group.MALFORMED, expert.severity.ERROR)
ef.invalid_edge_count = ProtoExpert.new("nodenet.invalid_edge_count", "Invalid edge count", 
                                       expert.group.MALFORMED, expert.severity.WARN)
ef.self_loop = ProtoExpert.new("nodenet.self_loop", "Self-loop edge detected", 
                              expert.group.PROTOCOL, expert.severity.NOTE)

-- Dissector function
function node_network_proto.dissector(buffer, pinfo, tree)
    local length = buffer:len()
    if length == 0 then return end
    
    -- Set protocol column
    pinfo.cols.protocol = node_network_proto.name
    
    -- Create protocol tree
    local subtree = tree:add(node_network_proto, buffer(), "Node Network Protocol")
    
    -- Determine packet type based on port and length
    local src_port = pinfo.src_port
    local dst_port = pinfo.dst_port
    local is_position_port = (src_port == 12345 or dst_port == 12345)
    local is_graph_port = (src_port == 12346 or dst_port == 12346)
    
    if is_position_port and length == 10 then
        dissect_position_packet(buffer, pinfo, subtree)
    elseif is_graph_port and length >= 4 then
        dissect_graph_packet(buffer, pinfo, subtree)
    else
        -- Unknown packet type
        subtree:add_proto_expert_info(ef.invalid_length)
        pinfo.cols.info = string.format("Unknown Node Network packet of length %d", length)
    end
end

-- Dissect position packet
function dissect_position_packet(buffer, pinfo, tree)
    -- Check minimum length
    if buffer:len() < 10 then
        tree:add_proto_expert_info(ef.invalid_length, string.format("Length is: %d", buffer:len()))
        return
    end
    
    -- Parse fields
    local node_id = buffer(0, 2):le_uint()
    local x = buffer(2, 4):le_float()
    local y = buffer(6, 4):le_float()
    
    -- Add to info column
    pinfo.cols.info = string.format("Position: Node %d at (%.2f, %.2f)", node_id, x, y)
    
    -- Add to tree
    tree:add_le(f.pos_node_id, buffer(0, 2)):append_text(string.format(" (Node %d)", node_id))
    tree:add_le(f.pos_x, buffer(2, 4)):append_text(string.format(" (%.2f)", x))
    tree:add_le(f.pos_y, buffer(6, 4)):append_text(string.format(" (%.2f)", y))
    
    -- Add summary
    local summary = tree:add(buffer(), string.format("Position Update: Node %d", node_id))
    summary:add(buffer(), string.format("Coordinates: (%.2f, %.2f)", x, y))
end

-- Dissect graph packet
function dissect_graph_packet(buffer, pinfo, tree)
    local length = buffer:len()
    
    -- Check minimum length for header
    if length < 4 then
        tree:add_proto_expert_info(ef.invalid_length)
        return
    end
    
    -- Parse header
    local sender_id = buffer(0, 2):le_uint()
    local edge_count = buffer(2, 2):le_uint()
    
    -- Validate edge count
    if edge_count > 50 then
        tree:add_proto_expert_info(ef.invalid_edge_count)
        edge_count = 50  -- Limit for safety
    end
    
    -- Check if we have enough data for all edges
    local expected_length = 4 + (edge_count * 6)
    if length < expected_length then
        tree:add_proto_expert_info(ef.invalid_length)
        -- Calculate how many complete edges we can parse
        edge_count = math.floor((length - 4) / 6)
    end
    
    -- Add to info column
    pinfo.cols.info = string.format("Graph: Node %d, %d edges", sender_id, edge_count)
    
    -- Add header fields to tree
    tree:add_le(f.graph_sender_id, buffer(0, 2)):append_text(string.format(" (Node %d)", sender_id))
    tree:add_le(f.graph_edge_count, buffer(2, 2)):append_text(string.format(" (%d edges)", edge_count))
    
    -- Add edges subtree
    if edge_count > 0 then
        local edges_tree = tree:add(buffer(4, edge_count * 6), 
                                   string.format("Edges (%d)", edge_count))
        
        local offset = 4
        for i = 1, edge_count do
            local edge_buffer = buffer(offset, 6)
            local source = edge_buffer(0, 2):le_uint()
            local target = edge_buffer(2, 2):le_uint()
            local strength = edge_buffer(4, 2):le_uint()
            
            -- Create edge subtree
            local edge_tree = edges_tree:add(edge_buffer, 
                             string.format("Edge %d: %d → %d (strength: %d)", 
                                         i, source, target, strength))
            
            -- Add individual fields
            edge_tree:add_le(f.edge_source, edge_buffer(0, 2)):append_text(string.format(" (Node %d)", source))
            edge_tree:add_le(f.edge_target, edge_buffer(2, 2)):append_text(string.format(" (Node %d)", target))
            edge_tree:add_le(f.edge_strength, edge_buffer(4, 2)):append_text(string.format(" (%d)", strength))
            
            -- Check for self-loops
            if source == target then
                edge_tree:add_proto_expert_info(ef.self_loop)
            end
            
            offset = offset + 6
        end
    end
    
    -- Add summary
    local summary = tree:add(buffer(), string.format("Graph from Node %d", sender_id))
    summary:add(buffer(), string.format("Contains %d connections", edge_count))
end

-- Register the dissector for UDP ports
local udp_port_table = DissectorTable.get("udp.port")
udp_port_table:add(12345, node_network_proto)  -- Position packets
udp_port_table:add(12346, node_network_proto)  -- Graph packets

-- Also register for heuristic dissection (optional)
function node_network_proto.heuristic(buffer, pinfo, tree)
    local length = buffer:len()
    local src_port = pinfo.src_port
    local dst_port = pinfo.dst_port
    
    -- Check if this looks like our protocol
    if (src_port == 12345 or dst_port == 12345) and length == 10 then
        -- Looks like a position packet
        node_network_proto.dissector(buffer, pinfo, tree)
        return true
    elseif (src_port == 12346 or dst_port == 12346) and length >= 4 then
        -- Looks like a graph packet
        node_network_proto.dissector(buffer, pinfo, tree)
        return true
    end
    
    return false
end

-- Register heuristic dissector
node_network_proto:register_heuristic("udp", node_network_proto.heuristic)

-- Print info message when loaded
print("Node Network Protocol dissector loaded")
print("Handles UDP ports 12345 (position) and 12346 (graph)")