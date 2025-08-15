import os
import json
import asyncio
import time
from pathlib import Path
import re
from openai import OpenAI
import base64
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def main():
    # Get environment variables
    input_dir = os.getenv("INPUT_DIR", "input")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    # Initialize OpenAI client
    client = OpenAI(api_key=openai_api_key)
    
    # Read the prompt
    with open("prompts/extract.json", "r") as f:
        prompt = f.read()
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Read all filenames in the input directory
    files = os.listdir(input_dir)
    
    # Extract tow IDs from form files
    tow_ids = set()
    for file in files:
        if file.endswith("_form.png"):
            match = re.match(r"tow_(\d+)_form\.png", file)
            if match:
                tow_ids.add(match.group(1))
    
    print(f"Found {len(tow_ids)} tows to process")
    
    for tow_id in sorted(tow_ids):
        form_path = os.path.join(input_dir, f"tow_{tow_id}_form.png")
        notes_path = os.path.join(input_dir, f"tow_{tow_id}_notes.png")
        output_path = os.path.join(output_dir, f"tow_{tow_id}.json")
        
        # Check if files exist
        if not os.path.exists(form_path):
            print(f"⚠️ Form file not found for tow {tow_id}")
            continue
            
        has_notes = os.path.exists(notes_path)
        
        # Prepare images for OpenAI Vision API
        messages = [
            {
                "role": "system", 
                "content": "You are a document parser for MOCNESS oceanographic tows."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encode_image(form_path)}"
                        }
                    }
                ]
            }
        ]
        
        # Add notes image if it exists
        if has_notes:
            messages[1]["content"].append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{encode_image(notes_path)}"
                }
            })
        
        try:
            # Call OpenAI API
            response = client.chat.completions.create(
                model="gpt-4o",
                temperature=0,
                messages=messages,
                max_tokens=4000
            )
            
            # Add delay after API call to avoid rate limiting
            await asyncio.sleep(1)
            
            # Extract and parse the result
            result_text = response.choices[0].message.content
            
            # Try to parse as JSON, if it fails, save as text
            try:
                result_json = json.loads(result_text)
                with open(output_path, "w") as f:
                    json.dump(result_json, f, indent=2)
            except json.JSONDecodeError:
                # If not valid JSON, save as text file
                output_path = output_path.replace('.json', '.txt')
                with open(output_path, "w") as f:
                    f.write(result_text)
            
            print(f"✅ Processed tow {tow_id}")
            
        except Exception as e:
            print(f"❌ Error processing tow {tow_id}: {str(e)}")

def encode_image(image_path):
    """Encode image to base64 string for OpenAI API"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

if __name__ == "__main__":
    asyncio.run(main())
