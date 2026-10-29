# Explicit operator action only: no format, resize, quota, or data deletion.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [Parameter(Mandatory=$true)][string]$ExpectedImageId,
    [Parameter(Mandatory=$true)][string]$ExpectedVolume,
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$AttachHelper
)
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrative operator required' }
$raw=& $PythonPath -m isycode.windows_sandbox_storage_cli inspect-image --image $ImagePath
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect selected image' }
$image=($raw -join "`n") | ConvertFrom-Json
$disks=@(Get-DiskImage -ImagePath $ImagePath | Get-Disk)
if ($disks.Count -ne 1 -or -not $image.fixed -or $image.device_id -ne 2 -or
    $image.virtual_bytes -ne 512MB -or $image.image_identifier -ne $ExpectedImageId) { throw 'Image identity mismatch' }
$disk=$disks[0]
if ($disk.IsBoot -or $disk.IsSystem -or $disk.Size -ne 512MB -or
    $image.physical_device -ne ('\\.\PhysicalDrive'+$disk.Number)) { throw 'Physical association mismatch' }
$volumes=@($disk | Get-Partition | ForEach-Object { $_.AccessPaths } | Where-Object { $_ -eq $ExpectedVolume })
if ($volumes.Count -ne 1) { throw 'Volume association mismatch' }
$allocations=@(Get-ChildItem -LiteralPath $ExpectedVolume -Directory -Force | Where-Object { $_.Name -like 'isycode-lpac-*' })
if ($allocations.Count) { throw 'Owned allocations remain; stop or recover them before remounting' }
& $PythonPath $AttachHelper --image $ImagePath --expected-image-id $ExpectedImageId
if ($LASTEXITCODE -ne 0) { throw 'Remount failed; preserve image and diagnose' }
$raw=& $PythonPath -m isycode.windows_sandbox_storage_cli inspect-image --image $ImagePath
if ($LASTEXITCODE -ne 0) { throw 'Post-remount image inspection failed' }
$after=($raw -join "`n") | ConvertFrom-Json
if ($after.image_identifier -ne $ExpectedImageId -or -not $after.physical_device) { throw 'Post-remount identity mismatch' }
$afterDisks=@(Get-DiskImage -ImagePath $ImagePath | Get-Disk)
if ($afterDisks.Count -ne 1 -or $afterDisks[0].IsBoot -or $afterDisks[0].IsSystem -or
    $afterDisks[0].Size -ne 512MB -or
    $after.physical_device -ne ('\\.\PhysicalDrive'+$afterDisks[0].Number)) { throw 'Post-remount physical association mismatch' }
$afterVolumes=@($afterDisks[0] | Get-Partition | ForEach-Object { $_.AccessPaths } | Where-Object { $_ -eq $ExpectedVolume })
if ($afterVolumes.Count -ne 1) { throw 'Post-remount volume association mismatch' }
Write-Output ('Remounted exact image: '+$ExpectedImageId)
