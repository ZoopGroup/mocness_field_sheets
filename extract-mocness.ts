import { chat, save, image, env } from "uv"
import fs from "fs/promises"
import path from "path"

const inputDir = env("INPUT_DIR") || "input"
const outputDir = env("OUTPUT_DIR") || "output"
const model = env("MODEL") || "gpt-5.3"
const prompt = await fs.readFile("prompts/extract.json", "utf-8")

// Read all filenames in the input directory
const files = await fs.readdir(inputDir)
const towIds = new Set(
  files
    .filter(f => /_form\.png$/i.test(f))
    .map(f => f.match(/tow_(\d+)_form\.png/i)?.[1])
    .filter(Boolean)
)

for (const towId of towIds) {
  const formPath = path.join(inputDir, `tow_${towId}_form.png`)
  const notesPath = path.join(inputDir, `tow_${towId}_notes.png`)
  const outputPath = path.join(outputDir, `tow_${towId}.json`)

  const formImage = await image.load(formPath)
  const hasNotes = await fs.stat(notesPath).then(() => true).catch(() => false)
  const notesImage = hasNotes ? await image.load(notesPath) : null

  const visionInputs = [formImage]
  if (notesImage) visionInputs.push(notesImage)

  const result = await chat({
    model,
    temperature: 0,
    messages: [
      { role: "system", content: "You are a document parser for MOCNESS oceanographic tows." },
      { role: "user", content: [{ type: "text", text: prompt }, ...visionInputs] }
    ]
  })

  await save(outputPath, result)
  console.log(`✅ Processed tow ${towId}`)
}
