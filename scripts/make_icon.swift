// Build launcher/Resources/AppIcon.icns from launcher/Resources/ProjectGravemindIcon.png.
import AppKit
import Foundation

let scriptURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
let repoRoot = scriptURL.deletingLastPathComponent().deletingLastPathComponent()
let sourceURL = repoRoot.appendingPathComponent("launcher/Resources/ProjectGravemindIcon.png")
let outputURL = repoRoot.appendingPathComponent("launcher/Resources/AppIcon.icns")
let fileManager = FileManager.default
let temp = fileManager.temporaryDirectory.appendingPathComponent("gravemind-icon-\(UUID().uuidString)")
let iconset = temp.appendingPathComponent("AppIcon.iconset")

func writePNG(source: NSImage, size: Int, name: String) throws {
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                        isPlanar: false, colorSpaceName: .deviceRGB,
                                        bytesPerRow: 0, bitsPerPixel: 0) else {
        throw NSError(domain: "make_icon", code: 1)
    }
    NSGraphicsContext.saveGraphicsState()
    let context = NSGraphicsContext(bitmapImageRep: bitmap)
    NSGraphicsContext.current = context
    context?.imageInterpolation = .high
    source.draw(in: NSRect(x: 0, y: 0, width: size, height: size),
                from: NSRect(origin: .zero, size: source.size), operation: .copy, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "make_icon", code: 2)
    }
    try data.write(to: iconset.appendingPathComponent(name))
}

do {
    guard let source = NSImage(contentsOf: sourceURL) else {
        throw NSError(domain: "make_icon", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "Icon source not found: \(sourceURL.path)"])
    }
    try fileManager.createDirectory(at: iconset, withIntermediateDirectories: true)
    for size in [16, 32, 128, 256, 512] {
        try writePNG(source: source, size: size, name: "icon_\(size)x\(size).png")
        try writePNG(source: source, size: size * 2, name: "icon_\(size)x\(size)@2x.png")
    }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
    process.arguments = ["-c", "icns", "-o", outputURL.path, iconset.path]
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw NSError(domain: "make_icon", code: Int(process.terminationStatus))
    }
    try? fileManager.removeItem(at: temp)
    print(outputURL.path)
} catch {
    try? fileManager.removeItem(at: temp)
    fputs("make_icon: \(error)\n", stderr)
    exit(1)
}
