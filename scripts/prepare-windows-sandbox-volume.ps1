# Operator-only provisioning. Never invoked by the product or test suite.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ImagePath,
    [Parameter(Mandatory=$true)][string]$OwnerSid,
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$ResultPath
)
$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrative operator session required. No disk operations performed.'
}
$ImagePath = [IO.Path]::GetFullPath($ImagePath)
if ($ImagePath.StartsWith('\\') -or [IO.Path]::GetExtension($ImagePath) -ne '.vhd') { throw 'Local new .vhd required' }
if (Test-Path -LiteralPath $ImagePath) { throw 'Existing image refused; never reuse or overwrite' }
if (Test-Path -LiteralPath $ResultPath) { throw 'Existing result refused' }
$owner = New-Object Security.Principal.SecurityIdentifier($OwnerSid)
$parent = Split-Path -Parent $ImagePath
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Explicit parent directory required' }
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($ImagePath).Substring(0,1))
if ($drive.Free -lt (512MB + 1GB)) { throw 'Insufficient backing-volume space' }
$diskpartFile = Join-Path $parent ('create-' + [guid]::NewGuid().ToString('N') + '.txt')
try {
    ('create vdisk file="' + $ImagePath + '" maximum=512 type=fixed') | Set-Content -LiteralPath $diskpartFile -Encoding ASCII
    & diskpart.exe /s $diskpartFile
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) { throw 'VHD creation failed' }
} finally { Remove-Item -LiteralPath $diskpartFile -ErrorAction SilentlyContinue }
$raw = & $PythonPath -m isycode.windows_sandbox_storage_cli inspect-image --image $ImagePath
if ($LASTEXITCODE -ne 0) { throw 'New image inspection failed' }
$newImage = ($raw -join "`n") | ConvertFrom-Json
& $PythonPath (Join-Path $PSScriptRoot 'attach-windows-sandbox-volume.py') --image $ImagePath --expected-image-id $newImage.image_identifier --new-attachment
if ($LASTEXITCODE -ne 0) { throw 'New image attachment failed; preserve it for diagnosis' }
function Get-VerifiedImageDisk {
    $raw = & $PythonPath -m isycode.windows_sandbox_storage_cli inspect-image --image $ImagePath
    if ($LASTEXITCODE -ne 0) { throw 'VirtDisk inspection failed; no formatting allowed' }
    $identity = ($raw -join "`n") | ConvertFrom-Json
    if ($identity.image_identifier -ne $newImage.image_identifier) { throw 'New image identity changed; no disk mutation allowed' }
    if (-not $identity.fixed -or $identity.device_id -ne 2 -or $identity.virtual_bytes -ne 512MB) { throw 'Image is not fixed classic 512 MiB VHD' }
    $disks = @(Get-DiskImage -ImagePath $ImagePath | Get-Disk)
    if ($disks.Count -ne 1) { throw 'Image/disk association ambiguous' }
    $disk = $disks[0]
    if ($disk.IsBoot -or $disk.IsSystem -or $disk.Size -ne 512MB -or
        $identity.physical_device -ne ('\\.\PhysicalDrive' + $disk.Number)) {
        throw 'Measured physical device does not match the newly created image'
    }
    return $disk
}
$disk = Get-VerifiedImageDisk
if ($disk.PartitionStyle -ne 'RAW') { throw 'Nonempty/initialized image refused' }
$disk | Initialize-Disk -PartitionStyle MBR
$disk = Get-VerifiedImageDisk
$partition = $disk | New-Partition -UseMaximumSize -AssignDriveLetter
$disk = Get-VerifiedImageDisk
if ($partition.DiskNumber -ne $disk.Number) { throw 'Partition association changed' }
$partition | Format-Volume -FileSystem NTFS -NewFileSystemLabel 'ISYCODE_SCRATCH' -Confirm:$false | Out-Null
$partition = Get-Partition -DiskNumber $disk.Number -PartitionNumber $partition.PartitionNumber
$guids = @($partition.AccessPaths | Where-Object { $_ -match '^\\\\\?\\Volume\{[a-fA-F0-9-]+\}\\$' })
if ($guids.Count -ne 1) { throw 'Persistent volume GUID unavailable' }
$volumeRoot = $guids[0]
foreach ($target in @($ImagePath, $volumeRoot)) {
    & icacls.exe $target /setowner ('*' + $OwnerSid)
    if ($LASTEXITCODE -ne 0) { throw 'Could not set operator ownership' }
}
# Set-Acl did not persist the protected volume-root DACL on this host. Use
# the same named Win32 security API consumed by the normal-user inspector.
@'
import sys
import win32security as security
owner, image, root = sys.argv[1:]
for target, inheritance in ((image, ''), (root, 'OICI')):
    descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f'D:P(A;{inheritance};FA;;;{owner})(A;{inheritance};FA;;;SY)', 1)
    security.SetNamedSecurityInfo(target, security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)
'@ | & $PythonPath - $OwnerSid $ImagePath $volumeRoot
if ($LASTEXITCODE -ne 0) { throw 'Private image/root DACL could not be applied' }
@{ image=$ImagePath; volume_guid=$volumeRoot; owner_sid=$OwnerSid; native_accepted=$false } |
    ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding UTF8
