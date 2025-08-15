import asyncio
from extract_mocness import main as extract_main

def main():
    print("Starting MOCNESS field sheet extraction...")
    asyncio.run(extract_main())

if __name__ == "__main__":
    main()
