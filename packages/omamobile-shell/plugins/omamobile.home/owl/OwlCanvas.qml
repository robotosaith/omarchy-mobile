// SPDX-License-Identifier: MIT
import QtQuick
import "paint.js" as Paint

// Canvas: asks the widget for this frame's drawing calls and paints them,
// in dp. One that read `time` repaints on the view's frame clock (30 fps at
// most, and only while the view is shown); any other only when its node,
// size or the theme changes.
//
// A frame of filled rectangles and circles only, moved, turned, clipped or
// faded (pixel art, bars, dots)
// is drawn as Rectangle items, which the scene graph batches on the GPU.
// A QML Canvas paints in software and uploads the whole image as a new
// texture every frame: two animated pixel-art widgets cost the phone more
// than a CPU core that way. Anything else still goes to the Canvas.
OwlNodeBase {
  id: canvasNode

  property bool readsTime: false
  readonly property var draw: canvasNode.node ? canvasNode.node.draw : null
  readonly property int frame: canvasNode.readsTime && canvasNode.view ? canvasNode.view.frame : 0

  // This frame's display list, for the Canvas, or its boxes, for the items.
  property var ops: null
  property var boxes: null
  // Rectangle items made so far: the pool only grows, so a frame with a
  // few more boxes than the last creates nothing new most of the time.
  property int pool: 0

  onReadsTimeChanged: if (canvasNode.view) canvasNode.view.noteAnimating(canvasNode, canvasNode.readsTime)
  Component.onDestruction: if (canvasNode.view) canvasNode.view.noteAnimating(canvasNode, false)

  readonly property var deps: [canvasNode.draw, canvasNode.innerW, canvasNode.innerH, canvasNode.frame,
                               canvasNode.view ? canvasNode.view.inkVersion : 0]
  onDepsChanged: Qt.callLater(canvasNode.refresh)

  function refresh() {
    const w = canvasNode.innerW, h = canvasNode.innerH
    if (!canvasNode.draw || w <= 0 || h <= 0) {
      canvasNode.ops = null
      canvasNode.boxes = null
      art.requestPaint()
      return
    }
    const dp = canvasNode.dp
    const ops = canvasNode.draw(w / dp, h / dp)
    // Told after this frame: a frame requested while drawing is lost.
    const reads = !!ops.readsTime
    if (reads !== canvasNode.readsTime) Qt.callLater(function() { canvasNode.readsTime = reads })
    const ratio = canvasNode.view ? canvasNode.view.devicePixelRatio : 1
    const list = Paint.boxes(ops, { foreground: String(canvasNode.ink("foreground")) }, w / dp, h / dp, dp * ratio)
    if (list) {
      if (list.length > canvasNode.pool) canvasNode.pool = list.length
      canvasNode.boxes = list
      if (canvasNode.ops) { canvasNode.ops = null; art.requestPaint() }
    } else {
      canvasNode.boxes = null
      canvasNode.ops = ops
      art.requestPaint()
    }
  }

  Item {
    id: blocks
    x: canvasNode.innerX
    y: canvasNode.innerY
    width: canvasNode.innerW
    height: canvasNode.innerH
    visible: canvasNode.boxes !== null
    // Straight boxes are already cut to the Canvas; turned ones may reach past it.
    clip: !!canvasNode.boxes && canvasNode.boxes.some(function(b) { return b.rotation !== 0 })

    Repeater {
      model: canvasNode.pool
      delegate: Rectangle {
        required property int index
        readonly property var box: canvasNode.boxes && index < canvasNode.boxes.length ? canvasNode.boxes[index] : null
        visible: box !== null
        x: box ? box.x * canvasNode.dp : 0
        y: box ? box.y * canvasNode.dp : 0
        width: box ? box.w * canvasNode.dp : 0
        height: box ? box.h * canvasNode.dp : 0
        radius: box ? box.radius * canvasNode.dp : 0
        color: box ? box.color : "transparent"
        opacity: box ? box.opacity : 1
        rotation: box ? box.rotation : 0
        antialiasing: radius > 0 || rotation !== 0
      }
    }
  }

  Canvas {
    id: art
    x: canvasNode.innerX
    y: canvasNode.innerY
    width: canvasNode.innerW
    height: canvasNode.innerH
    visible: canvasNode.boxes === null
    renderStrategy: Canvas.Cooperative
    onImageLoaded: requestPaint()

    function image(src) {
      const url = canvasNode.view ? canvasNode.view.imageUrl(src) : ""
      if (!url) return null
      if (art.isImageLoaded(url)) return url
      if (!art.isImageLoading(url) && !art.isImageError(url)) art.loadImage(url)
      return null
    }

    onPaint: {
      const ctx = getContext("2d")
      ctx.reset()
      const ops = canvasNode.ops
      if (!ops || width <= 0 || height <= 0) return
      const dp = canvasNode.dp
      ctx.scale(dp, dp)
      const ratio = canvasNode.view ? canvasNode.view.devicePixelRatio : 1
      Paint.paintList(ctx, ops, { foreground: canvasNode.ink("foreground") },
                      canvasNode.view ? canvasNode.view.family("sans") : "sans-serif", art.image, dp * ratio)
    }
  }
}
