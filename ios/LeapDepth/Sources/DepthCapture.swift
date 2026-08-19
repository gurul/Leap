// RGB+depth capture: AVFoundation's synchronized depth cameras.
//
// AVCaptureDataOutputSynchronizer hands us pixel-aligned (video, depth)
// pairs — the whole reason this app exists, since Safari can stream RGB but
// never depth. Front = TrueDepth (dense, made for 25-70cm — the desk
// range); rear = LiDAR (sparse zones upsampled, works 0.25-5m).

import AVFoundation
import Compression
import CoreImage
import simd

struct FramePacket {
    let timestampUs: UInt64
    let camera: UInt8               // 0 = front TrueDepth, 1 = rear LiDAR
    let intrinsics: simd_float4     // fx, fy, cx, cy at the streamed size
    let depthWidth: UInt16
    let depthHeight: UInt16
    let jpeg: Data
    let depthDeflate: Data          // raw DEFLATE of u16 millimetres
}

final class DepthCapture: NSObject, AVCaptureDataOutputSynchronizerDelegate {
    let session = AVCaptureSession()
    var onFrame: ((FramePacket) -> Void)?

    private let videoOutput = AVCaptureVideoDataOutput()
    private let depthOutput = AVCaptureDepthDataOutput()
    private var synchronizer: AVCaptureDataOutputSynchronizer?
    private let queue = DispatchQueue(label: "leapdepth.capture", qos: .userInteractive)
    private let ciContext = CIContext(options: [.cacheIntermediates: false])
    private var cameraCode: UInt8 = 0

    func configure(front: Bool) throws {
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        session.inputs.forEach(session.removeInput)
        session.outputs.forEach(session.removeOutput)
        session.sessionPreset = .vga640x480
        cameraCode = front ? 0 : 1

        let type: AVCaptureDevice.DeviceType =
            front ? .builtInTrueDepthCamera : .builtInLiDARDepthCamera
        guard let device = AVCaptureDevice.default(
            type, for: .video, position: front ? .front : .back) else {
            throw NSError(domain: "LeapDepth", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "no \(front ? "TrueDepth" : "LiDAR") camera"])
        }
        let input = try AVCaptureDeviceInput(device: device)
        session.addInput(input)

        videoOutput.videoSettings =
            [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        videoOutput.alwaysDiscardsLateVideoFrames = true
        session.addOutput(videoOutput)
        session.addOutput(depthOutput)
        depthOutput.isFilteringEnabled = true   // hole-filled, temporally smoothed

        // Highest-resolution Float16 depth the active format offers.
        let depthFormats = device.activeFormat.supportedDepthDataFormats.filter {
            CMFormatDescriptionGetMediaSubType($0.formatDescription)
                == kCVPixelFormatType_DepthFloat16
        }
        if let best = depthFormats.max(by: {
            CMVideoFormatDescriptionGetDimensions($0.formatDescription).width
                < CMVideoFormatDescriptionGetDimensions($1.formatDescription).width
        }) {
            try device.lockForConfiguration()
            device.activeDepthDataFormat = best
            device.unlockForConfiguration()
        }

        if let conn = videoOutput.connection(with: .video),
           conn.isCameraIntrinsicMatrixDeliverySupported {
            conn.isCameraIntrinsicMatrixDeliveryEnabled = true
        }

        let sync = AVCaptureDataOutputSynchronizer(
            dataOutputs: [videoOutput, depthOutput])
        sync.setDelegate(self, queue: queue)
        synchronizer = sync
    }

    func dataOutputSynchronizer(_ synchronizer: AVCaptureDataOutputSynchronizer,
                                didOutput collection: AVCaptureSynchronizedDataCollection) {
        guard
            let video = collection.synchronizedData(for: videoOutput)
                as? AVCaptureSynchronizedSampleBufferData,
            !video.sampleBufferWasDropped,
            let depth = collection.synchronizedData(for: depthOutput)
                as? AVCaptureSynchronizedDepthData,
            !depth.depthDataWasDropped,
            let pixels = CMSampleBufferGetImageBuffer(video.sampleBuffer)
        else { return }

        // Intrinsics ride each sample buffer once delivery is enabled.
        var intrinsics = simd_float4(0, 0, 0, 0)
        if let att = CMGetAttachment(
            video.sampleBuffer,
            key: kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix,
            attachmentModeOut: nil) as? Data {
            att.withUnsafeBytes { raw in
                let m = raw.load(as: matrix_float3x3.self)
                intrinsics = simd_float4(m[0][0], m[1][1], m[2][0], m[2][1])
            }
        }

        guard let jpeg = jpegData(from: pixels),
              let (deflated, w, h) = depthMillimetres(depth.depthData)
        else { return }

        let ts = CMSampleBufferGetPresentationTimeStamp(video.sampleBuffer)
        onFrame?(FramePacket(
            timestampUs: UInt64(max(0, ts.seconds) * 1_000_000),
            camera: cameraCode, intrinsics: intrinsics,
            depthWidth: UInt16(w), depthHeight: UInt16(h),
            jpeg: jpeg, depthDeflate: deflated))
    }

    private func jpegData(from pixels: CVPixelBuffer) -> Data? {
        let image = CIImage(cvPixelBuffer: pixels)
        return ciContext.jpegRepresentation(
            of: image, colorSpace: CGColorSpaceCreateDeviceRGB(),
            options: [kCGImageDestinationLossyCompressionQuality
                        as CIImageRepresentationOption: 0.5])
    }

    /// Depth -> u16 millimetres (0 = invalid), raw-DEFLATE compressed.
    /// The Mac side inflates with zlib wbits=-15 (Compression framework's
    /// ZLIB is raw DEFLATE — no zlib header or checksum).
    private func depthMillimetres(_ depthData: AVDepthData) -> (Data, Int, Int)? {
        let converted = depthData.converting(
            toDepthDataType: kCVPixelFormatType_DepthFloat32)
        let map = converted.depthDataMap
        CVPixelBufferLockBaseAddress(map, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(map, .readOnly) }
        let w = CVPixelBufferGetWidth(map)
        let h = CVPixelBufferGetHeight(map)
        guard let base = CVPixelBufferGetBaseAddress(map) else { return nil }
        let stride = CVPixelBufferGetBytesPerRow(map) / MemoryLayout<Float32>.size

        var mm = [UInt16](repeating: 0, count: w * h)
        base.withMemoryRebound(to: Float32.self, capacity: stride * h) { src in
            for y in 0..<h {
                for x in 0..<w {
                    let d = src[y * stride + x]
                    mm[y * w + x] = (d.isFinite && d > 0)
                        ? UInt16(clamping: Int(d * 1000.0)) : 0
                }
            }
        }
        let raw = mm.withUnsafeBufferPointer { Data(buffer: $0) }
        guard let deflated = deflate(raw) else { return nil }
        return (deflated, w, h)
    }

    private func deflate(_ data: Data) -> Data? {
        let capacity = data.count + 64 * 1024
        let dst = UnsafeMutablePointer<UInt8>.allocate(capacity: capacity)
        defer { dst.deallocate() }
        let written = data.withUnsafeBytes { raw -> Int in
            compression_encode_buffer(
                dst, capacity,
                raw.bindMemory(to: UInt8.self).baseAddress!, data.count,
                nil, COMPRESSION_ZLIB)
        }
        return written > 0 ? Data(bytes: dst, count: written) : nil
    }
}
