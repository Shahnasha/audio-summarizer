import os
import tempfile
import librosa
import soundfile as sf
import numpy as np


def save_wav_mono_16k(input_path, out_path, target_sr=16000):
    """
    Load an audio file and save as 16 kHz mono WAV (PCM16).
    Supports WAV, MP3, FLAC, OGG, M4A, and WebM (browser recordings).
    
    Args:
        input_path: Path to input audio file
        out_path: Path to output WAV file
        target_sr: Target sample rate (default: 16000 Hz for Vosk)
    
    Raises:
        ValueError: If audio file is invalid or cannot be processed
    """
    try:
        y, sr = _load_audio(input_path)
        
        # Handle stereo to mono conversion
        if y.ndim > 1:
            y = np.mean(y, axis=0)
        
        # Resample if needed
        if sr != target_sr:
            y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
        
        # Normalize to prevent clipping
        max_val = np.max(np.abs(y))
        if max_val > 0:
            y = y / max_val
        else:
            raise ValueError("Audio file contains only silence")
        
        # Save as 16-bit PCM WAV
        sf.write(out_path, y, samplerate=target_sr, subtype='PCM_16')
        
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to process audio file: {str(e)}")


def _load_audio(input_path):
    """
    Load audio from file, with pydub fallback for formats
    librosa may not handle natively (e.g., webm).
    
    Returns:
        tuple: (audio_array, sample_rate)
    """
    ext = os.path.splitext(input_path)[1].lower()
    
    # For webm files, convert via pydub first (needs ffmpeg)
    if ext in ('.webm',):
        return _load_via_pydub(input_path)
    
    # Try librosa first (handles most formats)
    try:
        y, sr = librosa.load(input_path, sr=None, mono=False)
        return y, sr
    except Exception:
        # Fallback to pydub for any format librosa can't handle
        return _load_via_pydub(input_path)


def _load_via_pydub(input_path):
    """
    Load audio using pydub (requires ffmpeg installed on system).
    Converts to temporary WAV then loads with librosa.
    
    Returns:
        tuple: (audio_array, sample_rate)
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ValueError(
            "pydub is required for this audio format. "
            "Install with: pip install pydub  "
            "(also requires ffmpeg on your system)"
        )
    
    tmp_wav_path = None
    try:
        # Load with pydub (uses ffmpeg under the hood)
        audio = AudioSegment.from_file(input_path)
        
        # Export as WAV to temp file
        tmp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp_wav_path = tmp_wav.name
        tmp_wav.close()
        
        audio.export(tmp_wav_path, format='wav')
        
        # Load the WAV with librosa
        y, sr = librosa.load(tmp_wav_path, sr=None, mono=False)
        return y, sr
        
    except Exception as e:
        raise ValueError(
            f"Failed to convert audio file: {str(e)}. "
            "Make sure ffmpeg is installed on your system."
        )
    finally:
        if tmp_wav_path and os.path.exists(tmp_wav_path):
            try:
                os.remove(tmp_wav_path)
            except Exception:
                pass