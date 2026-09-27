Add-Type -AssemblyName System.Drawing
$beforeDir = Join-Path $PSScriptRoot 'quiet-listening'
$afterDir = Join-Path $PSScriptRoot 'cc3'
$canvas = New-Object System.Drawing.Bitmap 552,606
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
$graphics.Clear([System.Drawing.Color]::FromArgb(28,30,32))
$font = New-Object System.Drawing.Font 'Arial',10
$brush = [System.Drawing.Brushes]::Gainsboro
$graphics.DrawString('Installed cc2: 12 px / y184', $font, $brush, 24, 10)
$graphics.DrawString('Revised cc3: 14 px / y160', $font, $brush, 288, 10)
$names = @('volume', 'windows')
for ($row = 0; $row -lt 2; $row++) {
    for ($column = 0; $column -lt 2; $column++) {
        $sourceDir = if ($column -eq 0) { $beforeDir } else { $afterDir }
        $native = [System.Drawing.Bitmap]::FromFile((Join-Path $sourceDir ($names[$row] + '.png')))
        $x = 24 + $column * 264
        $y = 38 + $row * 276
        $aperture = New-Object System.Drawing.Drawing2D.GraphicsPath
        $aperture.AddEllipse($x, $y, 240, 240)
        $graphics.SetClip($aperture)
        $graphics.DrawImageUnscaled($native, $x, $y)
        $graphics.ResetClip()
        $aperture.Dispose()
        $native.Dispose()
    }
}
$graphics.DrawString('Native LVGL renders. Viewing-angle acceptance remains a physical check.', $font, $brush, 24, 577)
$target = Join-Path $afterDir 'cc2-cc3-comparison.png'
$canvas.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
$font.Dispose()
$graphics.Dispose()
$canvas.Dispose()
Write-Output $target
