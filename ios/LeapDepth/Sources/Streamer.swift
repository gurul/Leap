// LPD1 wire protocol over plain TCP, phone -> Mac.
//
// One-hop LAN, so no congestion control theatre — the lesson the WebRTC
// path earned the hard way. Backpressure is freshest-frame-wins ON THE
// PHONE: a one-slot outbox where a new frame replaces an unsent one, so the
// Mac can never be fed the past. IMU samples are tiny and sent directly.

import CoreMotion
import Foundation
import Network

final class Streamer {
    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "leapdepth.net", qos: .userInteractive)
    private var slot: Data?             // newest un-sent frame, nil when idle
    private var sending = false
    private let motion = CMMotionManager()
    private(set) var framesSent = 0
    var onStatus: ((String) -> Void)?

    func start(host: String, port: UInt16) {
        stop()
        let conn = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        connection = conn
        conn.stateUpdateHandler = { [weak self] state in
            self?.onStatus?("\(state)")
        }
        conn.start(queue: queue)
        startIMU()
    }

    func stop() {
        motion.stopAccelerometerUpdates()
        connection?.cancel()
        connection = nil
        slot = nil
        sending = false
    }

    func send(_ packet: FramePacket) {
        var msg = Data(capacity: packet.jpeg.count + packet.depthDeflate.count + 64)
        msg.append(UInt8(0x01))
        appendLE(&msg, packet.timestampUs)
        msg.append(packet.camera)
        appendLE(&msg, packet.intrinsics.x)     // fx
        appendLE(&msg, packet.intrinsics.y)     // fy
        appendLE(&msg, packet.intrinsics.z)     // cx
        appendLE(&msg, packet.intrinsics.w)     // cy
        appendLE(&msg, packet.depthWidth)
        appendLE(&msg, packet.depthHeight)
        appendLE(&msg, UInt32(packet.jpeg.count))
        appendLE(&msg, UInt32(packet.depthDeflate.count))
        msg.append(packet.jpeg)
        msg.append(packet.depthDeflate)
        queue.async { [weak self] in
            guard let self else { return }
            self.slot = msg                     // newest wins; unsent is stale
            self.pump()
        }
    }

    private func pump() {
        guard !sending, let conn = connection, let msg = slot else { return }
        slot = nil
        sending = true
        conn.send(content: msg, completion: .contentProcessed { [weak self] _ in
            guard let self else { return }
            self.framesSent += 1
            self.sending = false
            self.pump()                         // drain whatever arrived meanwhile
        })
    }

    private func startIMU() {
        guard motion.isAccelerometerAvailable else { return }
        motion.accelerometerUpdateInterval = 0.2
        motion.startAccelerometerUpdates(to: OperationQueue()) { [weak self] data, _ in
            guard let self, let a = data?.acceleration,
                  let conn = self.connection else { return }
            var msg = Data(capacity: 21)
            msg.append(UInt8(0x02))
            appendLE(&msg, UInt64(Date().timeIntervalSince1970 * 1_000_000))
            // CoreMotion reports in g; the wire speaks m/s^2 like DeviceMotion.
            appendLE(&msg, Float32(a.x * 9.81))
            appendLE(&msg, Float32(a.y * 9.81))
            appendLE(&msg, Float32(a.z * 9.81))
            conn.send(content: msg, completion: .contentProcessed { _ in })
        }
    }
}

private func appendLE<T: FixedWidthInteger>(_ data: inout Data, _ value: T) {
    var v = value.littleEndian
    withUnsafeBytes(of: &v) { data.append(contentsOf: $0) }
}

private func appendLE(_ data: inout Data, _ value: Float32) {
    appendLE(&data, value.bitPattern)
}
