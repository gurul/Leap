// LeapDepth: the iPhone's depth cameras as a Leap source.
//
// The deliberate exception to Leap's no-install principle: Safari can
// stream RGB but Apple exposes no depth to the web, so real metric depth
// (TrueDepth front / LiDAR rear) needs this thin native sensor node. It
// captures synchronized RGB+depth and streams LPD1 over TCP to the Mac —
// run `python -m leapinput.phonedepth` there first; it prints the address.

import AVFoundation
import SwiftUI

@main
struct LeapDepthApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

final class Controller: ObservableObject {
    @Published var status = "idle"
    @Published var running = false
    private let capture = DepthCapture()
    private let streamer = Streamer()
    private var statsTimer: Timer?

    func start(host: String, front: Bool) {
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            DispatchQueue.main.async {
                guard let self else { return }
                guard granted else { self.status = "camera access denied"; return }
                do {
                    try self.capture.configure(front: front)
                } catch {
                    self.status = "\(error.localizedDescription)"
                    return
                }
                self.capture.onFrame = { [weak self] packet in
                    self?.streamer.send(packet)
                }
                self.streamer.onStatus = { [weak self] s in
                    DispatchQueue.main.async { self?.status = s }
                }
                self.streamer.start(host: host, port: 8447)
                self.capture.session.startRunning()
                self.running = true
                UIApplication.shared.isIdleTimerDisabled = true
                self.statsTimer = Timer.scheduledTimer(
                    withTimeInterval: 2.0, repeats: true) { [weak self] _ in
                    guard let self else { return }
                    self.status = "streaming — \(self.streamer.framesSent) frames"
                }
            }
        }
    }

    func stop() {
        statsTimer?.invalidate()
        capture.session.stopRunning()
        streamer.stop()
        running = false
        status = "stopped"
        UIApplication.shared.isIdleTimerDisabled = false
    }
}

struct ContentView: View {
    @AppStorage("host") private var host = "192.168.87.75"
    @AppStorage("front") private var front = true
    @StateObject private var controller = Controller()

    var body: some View {
        VStack(spacing: 16) {
            Text("LeapDepth").font(.largeTitle.bold())
            Text("RGB + depth → your Mac").foregroundStyle(.secondary)
            TextField("Mac IP (phonedepth prints it)", text: $host)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.decimalPad)
                .padding(.horizontal)
            Picker("camera", selection: $front) {
                Text("Front · TrueDepth (desk range)").tag(true)
                Text("Rear · LiDAR").tag(false)
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            Button(controller.running ? "Stop" : "Start") {
                controller.running
                    ? controller.stop()
                    : controller.start(host: host, front: front)
            }
            .font(.title2.bold())
            .buttonStyle(.borderedProminent)
            Text(controller.status)
                .font(.footnote.monospaced())
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.top, 40)
    }
}
