import fitz
import io

def test_invalid_toc():
    # Create a simple PDF
    doc = fitz.open()
    doc.new_page()
    
    # Try an invalid TOC: jump from 1 to 3
    toc = [
        [1, "Chapter 1", 1],
        [3, "Sub-Sub-Chapter", 1]
    ]
    
    print("Setting TOC...")
    doc.set_toc(toc)
    print("TOC Set successfully.")

    print("Attempting doc.write()...")
    try:
        out = doc.write()
        print("Success!")
    except Exception as e:
        print(f"Error during doc.write(): {type(e).__name__}: {str(e)}")

    doc.close()

if __name__ == "__main__":
    test_invalid_toc()
