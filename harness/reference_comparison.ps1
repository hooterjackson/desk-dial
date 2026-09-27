param([Parameter(Mandatory = $true)][string]$imagePath)
Add-Type -AssemblyName System.Drawing
$renderDir = Join-Path $PSScriptRoot 'quiet-listening'
$reference = [System.Drawing.Bitmap]::FromFile($imagePath)
$native = [System.Drawing.Bitmap]::FromFile((Join-Path $renderDir 'volume.png'))
$crop = New-Object System.Drawing.Bitmap 240,240
$cropGraphics = [System.Drawing.Graphics]::FromImage($crop)
$cropGraphics.Clear([System.Drawing.Color]::FromArgb(28,30,32))
$aperture = New-Object System.Drawing.Drawing2D.GraphicsPath
$aperture.AddEllipse(0,0,240,240)
$cropGraphics.SetClip($aperture)
$cropGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
# Approximate inner LCD aperture in the selected conceptual device image.
# This normalization is for design comparison, not a physical device capture.
$cropGraphics.DrawImage($reference, [System.Drawing.Rectangle]::new(0,0,240,240), [System.Drawing.Rectangle]::new(300,171,655,655), [System.Drawing.GraphicsUnit]::Pixel)
$crop.Save((Join-Path $renderDir 'reference-lcd-normalized.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$canvas = New-Object System.Drawing.Bitmap 552,302
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
$graphics.Clear([System.Drawing.Color]::FromArgb(28,30,32))
$font = New-Object System.Drawing.Font 'Arial',10
$brush = [System.Drawing.Brushes]::Gainsboro
$graphics.DrawString('Selected concept - normalized', $font, $brush, 24, 10)
$graphics.DrawString('Actual LVGL - native 240 px', $font, $brush, 288, 10)
$graphics.DrawImageUnscaled($crop,24,38)
$nativeAperture = New-Object System.Drawing.Drawing2D.GraphicsPath
$nativeAperture.AddEllipse(288,38,240,240)
$graphics.SetClip($nativeAperture)
$graphics.DrawImageUnscaled($native,288,38)
$canvas.Save((Join-Path $renderDir 'quiet-reference-comparison.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$font.Dispose()
$graphics.Dispose()
$canvas.Dispose()
$cropGraphics.Dispose()
$crop.Dispose()
$native.Dispose()
$reference.Dispose()
$aperture.Dispose()
$nativeAperture.Dispose()
Write-Output (Join-Path $renderDir 'quiet-reference-comparison.png')
