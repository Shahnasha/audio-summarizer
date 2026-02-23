import json
import wave
from vosk import Model, KaldiRecognizer


def transcribe_file(wav_path, model_path):
    """
    Transcribe a 16kHz mono WAV file using Vosk ASR model.
    
    Args:
        wav_path: Path to WAV file (must be 16kHz mono PCM16)
        model_path: Path to Vosk model directory
    
    Returns:
        tuple: (full_transcript_text, segments_list)
            - full_transcript_text: Complete transcription as string
            - segments_list: List of dicts with 'text', 'start', 'end' keys
    
    Raises:
        ValueError: If WAV format is incorrect
        Exception: If model loading or transcription fails
    """
    try:
        # Load Vosk model (cached internally by Vosk)
        model = Model(model_path)
    except Exception as e:
        raise Exception(f"Failed to load Vosk model from {model_path}: {str(e)}")

    # Open WAV file
    try:
        wf = wave.open(wav_path, "rb")
    except Exception as e:
        raise ValueError(f"Failed to open WAV file: {str(e)}")
    
    # Validate WAV format
    if wf.getnchannels() != 1:
        wf.close()
        raise ValueError(f"WAV must be mono (1 channel), got {wf.getnchannels()} channels")
    
    if wf.getsampwidth() != 2:
        wf.close()
        raise ValueError(f"WAV must be 16-bit (2 bytes), got {wf.getsampwidth()} bytes")
    
    if wf.getframerate() != 16000:
        wf.close()
        raise ValueError(f"WAV must be 16kHz, got {wf.getframerate()}Hz")

    # Initialize recognizer
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)  # Enable word-level timestamps

    segments = []
    
    try:
        # Process audio in chunks
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                
                # Extract text segment
                if 'text' in result and result['text'].strip():
                    seg = {'text': result['text'].strip()}
                    
                    # Add timestamps if available
                    if 'result' in result and len(result['result']) > 0:
                        seg['start'] = result['result'][0].get('start', 0)
                        seg['end'] = result['result'][-1].get('end', 0)
                    
                    segments.append(seg)
        
        # Get final result
        final = json.loads(rec.FinalResult())
        if 'text' in final and final['text'].strip():
            seg = {'text': final['text'].strip()}
            
            if 'result' in final and len(final['result']) > 0:
                seg['start'] = final['result'][0].get('start', 0)
                seg['end'] = final['result'][-1].get('end', 0)
            
            segments.append(seg)
    
    finally:
        wf.close()

    # Build full transcript from segments
    full_transcript = " ".join([s.get('text', '').strip() for s in segments])
    
    return full_transcript, segments