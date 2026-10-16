.pragma library
// SPDX-License-Identifier: MIT
// Paints an OWL Canvas display list (runtime.js drawCalls) onto a QML
// Canvas 2D context, in dp (the context is scaled by dp first). Also the
// Ring and Sparkline drawings. Angles are degrees from 12 o'clock,
// clockwise, as the guide has them.

function n(v, fallback) { return typeof v === "number" && isFinite(v) ? v : fallback }
function toRad(deg) { return (deg - 90) * Math.PI / 180 }

// A fill or stroke: a colour string, or { gradient: {radial, coords, colors} }.
function style(ctx, value) {
  if (value === null || value === undefined) return null
  if (typeof value === "string") return value
  if (!value.gradient) return null
  var g = value.gradient
  var grad = g.radial
    ? ctx.createRadialGradient(g.coords[0], g.coords[1], 0, g.coords[0], g.coords[1], Math.max(g.coords[2], 0.001))
    : ctx.createLinearGradient(g.coords[0], g.coords[1], g.coords[2], g.coords[3])
  var stops = g.colors.length
  for (var i = 0; i < stops; i++) if (g.colors[i]) grad.addColorStop(stops === 1 ? 0 : i / (stops - 1), g.colors[i])
  return grad
}

// Fill and/or stroke the path `trace` makes. Without either, a shape is
// filled with `color` (or the foreground); a line is stroked with it.
function shape(ctx, op, ink, trace, strokeByDefault) {
  var fill = style(ctx, op.fill)
  var stroke = style(ctx, op.stroke)
  if (fill === null && stroke === null) {
    var plain = style(ctx, op.color) || ink.foreground
    if (strokeByDefault) stroke = plain
    else fill = plain
  }
  ctx.beginPath()
  trace()
  if (fill !== null) {
    ctx.fillStyle = fill
    ctx.fill()
  }
  if (stroke !== null) {
    ctx.strokeStyle = stroke
    ctx.lineWidth = n(op.width, 1)
    ctx.lineCap = op.cap === "round" || op.cap === "square" ? op.cap : "butt"
    ctx.lineJoin = op.cap === "round" ? "round" : "miter"
    ctx.stroke()
  }
}

function roundedRect(ctx, x, y, w, h, r) {
  if (w < 0) { x += w; w = -w }
  if (h < 0) { y += h; h = -h }
  var radius = Math.max(0, Math.min(r, w / 2, h / 2))
  if (radius <= 0) { ctx.rect(x, y, w, h); return }
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}

// `pixel`: sprite rects land on whole device pixels, so no seams show.
function snapped(v, scale) { return Math.round(v * scale) / scale }

function paintList(ctx, ops, ink, font, images, scale) {
  for (var i = 0; i < ops.length; i++) paintOne(ctx, ops[i], ink, font, images, scale)
}

function group(ctx, op, ink, font, images, scale, setup) {
  ctx.save()
  setup()
  paintList(ctx, op.ops || [], ink, font, images, scale)
  ctx.restore()
}

function paintOne(ctx, op, ink, font, images, scale) {
  var a = op.args || []
  function arg(i) { return n(a[i], 0) }
  switch (op.op) {
  case "rect":
    if (op.pixel) {
      var x0 = snapped(arg(0), scale), y0 = snapped(arg(1), scale)
      var x1 = snapped(arg(0) + arg(2), scale), y1 = snapped(arg(1) + arg(3), scale)
      shape(ctx, op, ink, function() { ctx.rect(x0, y0, x1 - x0, y1 - y0) })
      return
    }
    shape(ctx, op, ink, function() { roundedRect(ctx, arg(0), arg(1), arg(2), arg(3), n(op.radius, 0)) })
    return
  case "circle":
    shape(ctx, op, ink, function() { ctx.arc(arg(0), arg(1), Math.max(arg(2), 0), 0, Math.PI * 2, false) })
    return
  case "arc": {
    var pie = (op.fill !== undefined && op.fill !== null) || op.stroke === undefined || op.stroke === null
    shape(ctx, op, ink, function() {
      if (pie) ctx.moveTo(arg(0), arg(1))
      ctx.arc(arg(0), arg(1), Math.max(arg(2), 0), toRad(arg(3)), toRad(arg(3) + arg(4)), arg(4) < 0)
      if (pie && (op.stroke === undefined || op.stroke === null)) ctx.closePath()
    })
    return
  }
  case "line":
    shape(ctx, { stroke: op.stroke || op.color || op.fill || null, width: op.width, cap: op.cap }, ink,
          function() { ctx.moveTo(arg(0), arg(1)); ctx.lineTo(arg(2), arg(3)) }, true)
    return
  case "path": {
    var pts = op.points || []
    if (!pts.length) return
    shape(ctx, op, ink, function() {
      ctx.moveTo(pts[0][0], pts[0][1])
      for (var k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1])
      if (op.closed) ctx.closePath()
    })
    return
  }
  case "text": {
    var size = n(op.size, 12)
    ctx.font = (op.bold ? "bold " : "") + size + "px \"" + font + "\""
    ctx.textAlign = op.align === "center" ? "center" : op.align === "end" ? "right" : "left"
    ctx.textBaseline = "middle"
    ctx.fillStyle = style(ctx, op.color || op.fill) || ink.foreground
    ctx.fillText(op.text, arg(1), arg(2))
    return
  }
  case "image": {
    var url = images ? images(op.src) : null
    if (url) ctx.drawImage(url, arg(1), arg(2), arg(3), arg(4))
    return
  }
  case "translate":
    group(ctx, op, ink, font, images, scale, function() { ctx.translate(arg(0), arg(1)) })
    return
  case "rotate":
    group(ctx, op, ink, font, images, scale, function() {
      ctx.translate(arg(1), arg(2))
      ctx.rotate(arg(0) * Math.PI / 180)
      ctx.translate(-arg(1), -arg(2))
    })
    return
  case "scale":
    group(ctx, op, ink, font, images, scale, function() {
      var sx = arg(0), sy = a.length > 1 ? arg(1) : sx
      ctx.translate(arg(2), arg(3))
      ctx.scale(sx, sy)
      ctx.translate(-arg(2), -arg(3))
    })
    return
  case "clip":
    group(ctx, op, ink, font, images, scale, function() {
      ctx.beginPath()
      ctx.rect(arg(0), arg(1), arg(2), arg(3))
      ctx.clip()
    })
    return
  case "layer":
    group(ctx, op, ink, font, images, scale, function() {
      ctx.globalAlpha = ctx.globalAlpha * Math.max(0, Math.min(1, n(a[0], 1)))
    })
    return
  }
}

// A display list made only of filled rectangles and circles (moved,
// turned, clipped and faded by translate, rotate, clip and layer) as plain
// boxes [{x, y, w, h, color, radius, opacity, rotation}] in dp, for the
// scene graph to draw on the GPU: x, y, w, h is the box before it turns
// about its centre by `rotation` degrees. null when anything else is in it
// (a stroke, a gradient, text, an image, a path, scale, or a clip inside a
// turn), and the Canvas paints it. `scale` is device pixels per dp, for
// `pixel` rects.
var MAX_BOXES = 1000
function boxes(ops, ink, width, height, scale) {
  var out = []
  function solid(op) {
    if (op.stroke !== undefined && op.stroke !== null) return null
    var fill = op.fill !== undefined && op.fill !== null ? op.fill : op.color
    if (fill === undefined || fill === null) return ink.foreground
    return typeof fill === "string" ? fill : null
  }
  // t: the transform so far, p -> R(t.deg) p + (t.x, t.y), with t.c/t.s
  // its cosine and sine; clip: the clip in canvas coordinates.
  function walk(list, t, clip, alpha) {
    for (var i = 0; i < list.length; i++) {
      var op = list[i], a = op.args || []
      var arg = function(k) { return n(a[k], 0) }
      if (op.op === "rect" || op.op === "circle") {
        var color = solid(op)
        if (color === null) return false
        var x, y, w, h, r
        if (op.op === "circle") {
          r = Math.max(arg(2), 0); x = arg(0) - r; y = arg(1) - r; w = h = 2 * r
        } else {
          x = arg(0); y = arg(1); w = arg(2); h = arg(3); r = Math.max(n(op.radius, 0), 0)
          if (w < 0) { x += w; w = -w }
          if (h < 0) { y += h; h = -h }
          if (op.pixel && t.deg === 0) {
            var x1 = snapped(x + w + t.x, scale) - t.x, y1 = snapped(y + h + t.y, scale) - t.y
            x = snapped(x + t.x, scale) - t.x; y = snapped(y + t.y, scale) - t.y; w = x1 - x; h = y1 - y
          }
          r = Math.min(r, w / 2, h / 2)
        }
        if (w <= 0 || h <= 0) continue
        if (out.length >= MAX_BOXES) return false
        if (t.deg !== 0) {
          // Turned: the box keeps its size and turns about its own centre.
          var mx = x + w / 2, my = y + h / 2
          var cx = t.c * mx - t.s * my + t.x, cy = t.s * mx + t.c * my + t.y
          out.push({ x: cx - w / 2, y: cy - h / 2, w: w, h: h, color: color, radius: r, opacity: alpha, rotation: t.deg })
          continue
        }
        x += t.x; y += t.y
        var l = Math.max(x, clip[0]), tp = Math.max(y, clip[1]), rr = Math.min(x + w, clip[2]), b = Math.min(y + h, clip[3])
        if (rr <= l || b <= tp) continue
        // A rounded shape cut by a clip can't be one box.
        if (r > 0 && (l > x || tp > y || rr < x + w || b < y + h)) return false
        out.push({ x: l, y: tp, w: rr - l, h: b - tp, color: color, radius: r, opacity: alpha, rotation: 0 })
      } else if (op.op === "translate") {
        var dx = arg(0), dy = arg(1)
        if (!walk(op.ops || [], { deg: t.deg, c: t.c, s: t.s, x: t.x + t.c * dx - t.s * dy, y: t.y + t.s * dx + t.c * dy }, clip, alpha)) return false
      } else if (op.op === "rotate") {
        // about (px, py): p -> R (p - pivot) + pivot, then the transform so far
        var deg = arg(0), px = arg(1), py = arg(2)
        var rad = deg * Math.PI / 180, c = Math.cos(rad), sn = Math.sin(rad)
        var qx = px - (c * px - sn * py), qy = py - (sn * px + c * py)
        var nt = { deg: t.deg + deg, c: t.c * c - t.s * sn, s: t.s * c + t.c * sn,
                   x: t.x + t.c * qx - t.s * qy, y: t.y + t.s * qx + t.c * qy }
        if (Math.abs(nt.deg % 360) < 1e-9) { nt.deg = 0; nt.c = 1; nt.s = 0 }
        if (!walk(op.ops || [], nt, clip, alpha)) return false
      } else if (op.op === "clip") {
        if (t.deg !== 0) return false
        var X = arg(0) + t.x, Y = arg(1) + t.y
        if (!walk(op.ops || [], t, [Math.max(clip[0], X), Math.max(clip[1], Y), Math.min(clip[2], X + arg(2)), Math.min(clip[3], Y + arg(3))], alpha)) return false
      } else if (op.op === "layer") {
        var f = Math.max(0, Math.min(1, n(a[0], 1)))
        if (!walk(op.ops || [], t, clip, alpha * f)) return false
      } else {
        return false
      }
    }
    return true
  }
  return walk(ops, { deg: 0, c: 1, s: 0, x: 0, y: 0 }, [0, 0, width, height], 1) ? out : null
}

// Every image a display list draws, so the Canvas can load them first.
function imageSources(ops, out) {
  var list = out || []
  for (var i = 0; i < ops.length; i++) {
    if (ops[i].op === "image" && ops[i].src && list.indexOf(ops[i].src) < 0) list.push(ops[i].src)
    if (ops[i].ops) imageSources(ops[i].ops, list)
  }
  return list
}

// Ring: a track and a value arc, `start`/`sweep` in degrees (a gauge is
// start 225, sweep 270), in pixels.
function ring(ctx, w, h, p, value, dp, ink) {
  var t = n(p.thickness, 6) * dp
  var r = Math.min(w, h) / 2 - t / 2
  if (r <= 0) return
  var start = n(p.start, 0), sweep = n(p.sweep, 360)
  var a0 = toRad(start)
  ctx.lineWidth = t
  ctx.lineCap = "round"
  ctx.strokeStyle = p.track || ink.surface
  ctx.beginPath()
  ctx.arc(w / 2, h / 2, r, a0, a0 + sweep * Math.PI / 180, false)
  ctx.stroke()
  if (value > 0) {
    ctx.strokeStyle = p.color || ink.accent
    ctx.beginPath()
    ctx.arc(w / 2, h / 2, r, a0, a0 + sweep * value * Math.PI / 180, false)
    ctx.stroke()
  }
}

// Sparkline: values scaled between min (0) and max (the peak plus
// headroom), an optional area under the line, in pixels.
function sparkline(ctx, w, h, p, dp, ink) {
  var values = Array.isArray(p.values) ? p.values : []
  var lo = n(p.min, 0)
  var hi = p.max
  if (typeof hi !== "number") {
    var peak = -Infinity
    values.forEach(function(v) { if (typeof v === "number") peak = Math.max(peak, v) })
    hi = Math.max(lo + (peak - lo) * 1.15, lo + 1)
  }
  if (!isFinite(hi) || hi <= lo) hi = lo + 1
  var count = values.length
  var pts = []
  for (var i = 0; i < count; i++) {
    if (typeof values[i] !== "number") continue
    pts.push([count > 1 ? i / (count - 1) * w : w / 2, h - (values[i] - lo) / (hi - lo) * h])
  }
  if (pts.length < 2) return
  var line = p.color || ink.accent
  if (p.area) {
    ctx.beginPath()
    ctx.moveTo(pts[0][0], h)
    pts.forEach(function(q) { ctx.lineTo(q[0], q[1]) })
    ctx.lineTo(pts[pts.length - 1][0], h)
    ctx.closePath()
    ctx.fillStyle = typeof p.area === "string" ? p.area : withAlpha(line, 0.2)
    ctx.fill()
  }
  ctx.beginPath()
  ctx.moveTo(pts[0][0], pts[0][1])
  pts.forEach(function(q) { ctx.lineTo(q[0], q[1]) })
  ctx.lineWidth = n(p.thickness, 2) * dp
  ctx.lineJoin = "round"
  ctx.lineCap = "round"
  ctx.strokeStyle = line
  ctx.stroke()
}

// "#aarrggbb" or "#rrggbb" with its alpha multiplied by `factor`.
function withAlpha(color, factor) {
  var s = String(color || "")
  var m = /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.exec(s)
  if (!m) return s
  var hex = m[1].length === 6 ? "ff" + m[1] : m[1]
  var a = Math.round(parseInt(hex.slice(0, 2), 16) * Math.max(0, Math.min(1, factor)))
  return "#" + (a < 16 ? "0" : "") + a.toString(16) + hex.slice(2)
}

if (typeof module !== "undefined") {
  module.exports = { paintList: paintList, boxes: boxes, imageSources: imageSources, ring: ring, sparkline: sparkline, withAlpha: withAlpha }
}
