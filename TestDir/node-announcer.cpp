#include <iostream>
#include <thread>
#include <vector>
#include <random>
#include <chrono>
#include <cstring>
#include <map>
#include <bitset>
#include <atomic>
#include <mutex>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
    typedef int socklen_t;
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #define SOCKET int
    #define INVALID_SOCKET -1
    #define SOCKET_ERROR -1
    #define closesocket close
#endif

#define NUM_NODES 20
#define MIN_EDGES 6
#define MAX_EDGES 35 // set max edges in packet to 50

struct PositionPacket {
    uint16_t node_id;
    // note because float is 4 byte but uint16 is 2, there is a 2 byte gap in the binary
    float x;
    float y;
};

struct GraphEdge {
    uint16_t source_id;
    uint16_t target_id;
    uint16_t strength;
};

struct GraphPacket {
    uint16_t sender_id;
    uint16_t edge_count;
    GraphEdge edges[50];
};

std::atomic<bool> running{true};
std::mutex lock;

class UDPServer {
private:
    SOCKET sock;
    sockaddr_in addr;
    
public:
    UDPServer(int port) {
#ifdef _WIN32
        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
            throw std::runtime_error("WSAStartup failed");
        }
#endif
        
        sock = socket(AF_INET, SOCK_DGRAM, 0);
        if (sock == INVALID_SOCKET) {
            throw std::runtime_error("Failed to create socket");
        }
        
        // Enable broadcast
        int broadcast = 1;
        if (setsockopt(sock, SOL_SOCKET, SO_BROADCAST, (char*)&broadcast, sizeof(broadcast)) < 0) {
            throw std::runtime_error("Failed to set broadcast option");
        }
        
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = inet_addr("127.0.0.1"); // Broadcast address
    }
    
    ~UDPServer() {
        closesocket(sock);
#ifdef _WIN32
        WSACleanup();
#endif
    }
    
    void sendPacket(const void* data, size_t size) {
        sendto(sock, (const char*)data, size, 0, (sockaddr*)&addr, sizeof(addr));
    }
};

class NodeManager {
private:
    std::vector<uint16_t> node_ids;
    std::map<uint16_t, std::pair<float, float>> positions;
    std::vector<std::vector<float>> distances; // adjacency mat
    std::random_device rd;
    std::mt19937 gen;
    std::uniform_real_distribution<float> pos_dist;
    std::uniform_real_distribution<float> move_dist;
    std::uniform_int_distribution<int> coin_toss;
    
public:
    NodeManager() : gen(rd()), pos_dist(0.0f, 1000.0f), move_dist(-5.0f, 5.0f), coin_toss(0,9) {
        for (int i = 1; i <= NUM_NODES; ++i) {
            node_ids.push_back(i);
            positions[i] = {pos_dist(gen), pos_dist(gen)};
            union {
                float f;
                uint32_t i;
            } u;
            u.f = positions[i].first;
            // std::cout << "Node " << i << ": x = " << u.f << " -> " << std::bitset<sizeof(float) * 8>(u.i) << ", y = " << positions[i].second << "\n";
            std::vector<float> temp;
            for (int j = 0; j < NUM_NODES; j++) {
                temp.push_back(0);
            }
            distances.push_back(temp);
        }

        for (int i = 0; i < NUM_NODES; i++) {
            uint16_t source_node = node_ids[i];
            for (int j = i + 1; j < NUM_NODES; j++) {
                uint16_t target_node = node_ids[j];
                float dist = getDistance(source_node, target_node);
                distances[i][j] = dist;
                distances[j][i] = dist;
            }
        }
    }
    
    void updatePositions() {
        for (auto& [id, pos] : positions) {
            if (coin_toss(gen) % 2) {
                pos.first += move_dist(gen);
                pos.second += move_dist(gen);
                
                pos.first = std::max(0.0f, std::min(1000.0f, pos.first));
                pos.second = std::max(0.0f, std::min(1000.0f, pos.second));
            }   
        }
    }
    
    const std::vector<uint16_t>& getNodeIds() const { return node_ids; }
    std::pair<float, float> getPosition(uint16_t id) const {
        auto it = positions.find(id);
        return it != positions.end() ? it->second : std::make_pair(0.0f, 0.0f);
    }

    float getDistance(uint16_t source_id, uint16_t target_id) {
        float dx = positions[source_id].first - positions[target_id].first;
        float dy = positions[source_id].second - positions[target_id].second;
        return std::sqrtf(dx*dx + dy*dy);
    } 
};

class GraphGenerator {
private:
    std::random_device rd;
    std::mt19937 gen;
    std::uniform_int_distribution<int> node_dist;
    std::uniform_int_distribution<uint16_t> strength_dist;
    std::uniform_int_distribution<int> edge_count_dist;
    
public:
    GraphGenerator() : gen(rd()), node_dist(1, NUM_NODES), strength_dist(1, 1000), edge_count_dist(MIN_EDGES, MAX_EDGES) {}
    
    GraphPacket generateGraph(uint16_t sender_id) {
        GraphPacket packet;
        packet.sender_id = sender_id;
        
        int num_edges = edge_count_dist(gen);
        packet.edge_count = num_edges;
        
        for (int i = 0; i < num_edges; ++i) {
            packet.edges[i].source_id = node_dist(gen);
            do {
                packet.edges[i].target_id = node_dist(gen);
            } while (packet.edges[i].target_id == packet.edges[i].source_id);
            
            packet.edges[i].strength = strength_dist(gen);
        }
        
        return packet;
    }
};

void positionServer() {
    try {
        UDPServer server(12345);
        NodeManager nodeManager;
        
        std::cout << "Position server started on port 12345\n";
        
        while (running) {
            nodeManager.updatePositions();
            
            for (uint16_t node_id : nodeManager.getNodeIds()) {
                PositionPacket packet;
                packet.node_id = node_id;
                auto pos = nodeManager.getPosition(node_id);
                packet.x = pos.first;
                packet.y = pos.second;

                // std::cout << "Position Packet Size: " << sizeof(packet) << "\n";
                union {
                    float f;
                    uint32_t i;
                } u;

                // std::cout << "\tid: " << packet.node_id << " -> " << std::bitset<8 * sizeof(uint16_t)>(packet.node_id) << "\n";
                u.f = packet.x;
                // std::cout << "\tx: " << packet.x << " -> " << std::bitset<8 * sizeof(float)>(u.i) << "\n";
                u.f = packet.y;
                // std::cout << "\ty: " << packet.y << " -> " << std::bitset<8 * sizeof(float)>(u.i) << "\n";
                
                uint16_t temp;
                std::memcpy(&temp, &packet, sizeof(temp));
                float tx, ty;
                void* pack_ptr = (void *)(&packet);

                std::memcpy(&tx, (void*)((char*)pack_ptr + 4), sizeof(float));
                std::memcpy(&ty, (void*)((char*)pack_ptr + 8), sizeof(float));
                // std::cout << "id:" << temp << ", x = " << tx << ", y = " << ty << "\n";

                std::memcpy((void*)((char*)pack_ptr + 2), &packet, sizeof(uint16_t));
                server.sendPacket((void*)((char*)pack_ptr + 2), sizeof(packet) - sizeof(uint16_t));
                std::this_thread::sleep_for(std::chrono::milliseconds(10));
            }
            
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        std::cout << "Position server stopped.\n";
    } catch (const std::exception& e) {
        std::cerr << "Position server error: " << e.what() << std::endl;
    }
}

void graphServer() {
    try {
        UDPServer server(12346);
        GraphGenerator graphGen;
        
        std::cout << "Graph server started on port 12346\n";
        
        while (running) {
            for (uint16_t node_id = 1; node_id <= NUM_NODES; ++node_id) {
                GraphPacket packet = graphGen.generateGraph(node_id);
                server.sendPacket(&packet, sizeof(GraphPacket) - sizeof(GraphEdge) * (50 - packet.edge_count));
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
            }
            
            std::this_thread::sleep_for(std::chrono::seconds(2));
        }

        std::cout << "Graph server stopped.\n";
    } catch (const std::exception& e) {
        std::cerr << "Graph server error: " << e.what() << std::endl;
    }
}

int main() {
    std::cout << "Starting UDP servers...\n";
    
    std::thread pos_thread(positionServer);
    std::thread graph_thread(graphServer);
    
    std::cout << "Servers running. Press Enter to stop...\n";
    std::cout << "Check of float: " << sizeof(float) << "bytes\n";
    
    std::cin.get();

     running = false;

    // Join threads
    if (pos_thread.joinable()) pos_thread.join();
    if (graph_thread.joinable()) graph_thread.join();

    std::cout << "Servers stopped. Exiting cleanly.\n";
    return 0;
}