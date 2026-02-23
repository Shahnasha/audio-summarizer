import re
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

SENTENCE_MODEL_NAME = "all-MiniLM-L6-v2"

# Global model cache
_model = None


def get_model():
    """
    Lazy load and cache the sentence transformer model.
    This avoids reloading the model on each request.
    """
    global _model
    if _model is None:
        try:
            _model = SentenceTransformer(SENTENCE_MODEL_NAME)
        except Exception as e:
            raise Exception(f"Failed to load sentence model '{SENTENCE_MODEL_NAME}': {str(e)}")
    return _model


def sentence_tokenize(text):
    """
    Simple offline sentence tokenizer using regex.
    Splits on sentence-ending punctuation (. ! ?)
    
    Args:
        text: Input text to tokenize
    
    Returns:
        list: List of sentence strings
    """
    if not text or not text.strip():
        return []

    # Split on period, exclamation, or question mark followed by whitespace
    # (?<=[.!?]) is a positive lookbehind for sentence endings
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # Filter out empty strings and whitespace-only strings
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # Remove very short "sentences" (likely artifacts)
    sentences = [s for s in sentences if len(s) > 3]
    
    return sentences


def summarize_extract(transcript_text, top_k=5):
    """
    Extractive summarization using sentence embeddings and cosine similarity.
    Selects the top_k sentences most similar to the document's mean embedding.
    
    Args:
        transcript_text: Full transcript text
        top_k: Number of top sentences to extract (default: 5)
    
    Returns:
        tuple: (summary_text, highlights_list)
            - summary_text: Summary with sentences in original order
            - highlights_list: List of dicts with 'sentence' and 'score' keys,
                             ordered by relevance score (highest first)
    """
    # Tokenize into sentences
    sentences = sentence_tokenize(transcript_text)
    
    if len(sentences) == 0:
        return "", []
    
    # Handle case where transcript has fewer sentences than requested
    if len(sentences) <= top_k:
        # Return all sentences in original order
        highlights = [
            {"sentence": sent, "score": 1.0} 
            for sent in sentences
        ]
        return transcript_text.strip(), highlights
    
    try:
        # Load embedding model
        model = get_model()
        
        # Generate embeddings for all sentences
        embeddings = model.encode(sentences, show_progress_bar=False)
        
        # Compute document-level embedding (mean of all sentence embeddings)
        doc_embedding = np.mean(embeddings, axis=0, keepdims=True)
        
        # Calculate cosine similarity of each sentence to document
        scores = cosine_similarity(embeddings, doc_embedding).flatten()
        
        # Get indices of top k sentences
        k = min(top_k, len(sentences))
        top_indices = np.argsort(scores)[-k:][::-1]  # Highest scores first
        
        # Create highlights list (ordered by score, descending)
        highlights = [
            {"sentence": sentences[i], "score": float(scores[i])}
            for i in top_indices
        ]
        
        # Create summary with sentences in original document order
        ordered_indices = sorted(top_indices)
        summary = " ".join(sentences[i] for i in ordered_indices)
        
        return summary, highlights
    
    except Exception as e:
        # Fallback: return first top_k sentences if embedding fails
        print(f"Warning: Summarization failed, using fallback: {e}")
        fallback_sentences = sentences[:top_k]
        highlights = [
            {"sentence": sent, "score": 0.0} 
            for sent in fallback_sentences
        ]
        return " ".join(fallback_sentences), highlights