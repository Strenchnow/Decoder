#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for Quick Convert
Generates test media files and verifies conversion
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path to import convert_media
sys.path.insert(0, str(Path(__file__).parent))

CREATE_NO_WINDOW = 0x08000000

def run_cmd(cmd, **kwargs):
    """Run command with CREATE_NO_WINDOW on Windows"""
    kwargs.setdefault('creationflags', CREATE_NO_WINDOW)
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('text', True)
    return subprocess.run(cmd, **kwargs)

def check_ffmpeg():
    """Check if ffmpeg is available"""
    result = run_cmd(['ffmpeg', '-version'])
    return result.returncode == 0

def generate_test_image(output_path: Path):
    """Generate a test image using ffmpeg"""
    print(f"Generating test image: {output_path}")
    # Create a color test pattern image
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=640x480:rate=1',
        '-frames:v', '1',
        '-update', '1',
        str(output_path)
    ]
    result = run_cmd(cmd)
    return result.returncode == 0

def generate_test_video(output_path: Path, duration=3):
    """Generate a test video using ffmpeg"""
    print(f"Generating test video: {output_path}")
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'testsrc2=size=640x480:rate=30',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=' + str(duration),
        '-t', str(duration),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '30',
        '-c:a', 'aac', '-b:a', '128k',
        '-pix_fmt', 'yuv420p',
        str(output_path)
    ]
    result = run_cmd(cmd)
    return result.returncode == 0

def test_conversion(input_path: Path, target_ext: str):
    """Test conversion using convert_media.py"""
    print(f"Testing conversion: {input_path.name} -> {target_ext}")
    cmd = [
        sys.executable, 'convert_media.py',
        str(input_path), target_ext
    ]
    result = run_cmd(cmd, timeout=60)
    if result.returncode == 0:
        # Check output file exists
        expected_output = input_path.with_suffix(f'.{target_ext}')
        if input_path.suffix.lower().lstrip('.') == target_ext:
            expected_output = input_path.with_stem(f"{input_path.stem}_converted").with_suffix(f'.{target_ext}')

        if expected_output.exists():
            size = expected_output.stat().st_size
            print(f"  SUCCESS: {expected_output.name} ({size} bytes)")
            return True, expected_output
        else:
            print(f"  FAIL: Output file not found: {expected_output}")
            return False, None
    else:
        print(f"  FAIL: {result.stderr[:200]}")
        return False, None

def main():
    print("=" * 60)
    print("Quick Convert - Test Suite")
    print("=" * 60)

    # Check ffmpeg
    if not check_ffmpeg():
        print("ERROR: ffmpeg not found!")
        print("Install with: winget install Gyan.FFmpeg")
        return 1

    print("ffmpeg: OK")
    print()

    # Create test directory
    test_dir = Path(__file__).parent / "test_files"
    test_dir.mkdir(exist_ok=True)

    # Clean previous test files
    for f in test_dir.glob("*"):
        try:
            f.unlink()
        except:
            pass

    # Generate test files
    test_image = test_dir / "test_image.png"
    test_video = test_dir / "test_video.mp4"

    print("Generating test files...")
    if not generate_test_image(test_image):
        print("Failed to generate test image")
        return 1

    if not generate_test_video(test_video):
        print("Failed to generate test video")
        return 1

    print("Test files generated successfully.")
    print()

    # Test conversions
    print("Running conversion tests...")
    print("-" * 40)

    results = []

    # Image conversions
    for ext in ['jpg', 'webp', 'ico']:
        success, out = test_conversion(test_image, ext)
        results.append((f"PNG -> {ext.upper()}", success))

    # Video conversions
    for ext in ['webm', 'avi', 'mkv', 'gif']:
        success, out = test_conversion(test_video, ext)
        results.append((f"MP4 -> {ext.upper()}", success))

    # Same format conversion (should add _converted suffix)
    success, out = test_conversion(test_image, 'png')
    results.append(("PNG -> PNG (suffix)", success))

    success, out = test_conversion(test_video, 'mp4')
    results.append(("MP4 -> MP4 (suffix)", success))

    # Summary
    print()
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s in results if s)
    total = len(results)
    for name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed}/{total} passed")

    if passed == total:
        print("\nAll tests PASSED!")
        return 0
    else:
        print(f"\n{total - passed} test(s) FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(main())