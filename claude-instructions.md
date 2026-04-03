## General tips for effective prompting

### 1. Be clear and specific
   - Clearly state your task or question at the beginning of your message.
   - Provide context and details to help Claude understand your needs.
   - Break complex tasks into smaller, manageable steps.

   Bad prompt:
   "Help me with a presentation."

   Good prompt:
   "I need help creating a 10-slide presentation for our quarterly sales meeting. The presentation should cover our Q2 sales performance, top-selling products, and sales targets for Q3. Please provide an outline with key points for each slide."

   Why it's better: The good prompt provides specific details about the task, including the number of slides, the purpose of the presentation, and the key topics to be covered.

### 2. Use examples
   - Provide examples of the kind of output you're looking for.
   - If you want a specific format or style, show Claude an example.

   Bad prompt:
   "Write a professional email."

   Good prompt:
   "I need to write a professional email to a client about a project delay. Here's a similar email I've sent before:

   'Dear [Client],
   I hope this email finds you well. I wanted to update you on the progress of [Project Name]. Unfortunately, we've encountered an unexpected issue that will delay our completion date by approximately two weeks. We're working diligently to resolve this and will keep you updated on our progress.
   Please let me know if you have any questions or concerns.
   Best regards,
   [Your Name]'

   Help me draft a new email following a similar tone and structure, but for our current situation where we're delayed by a month due to supply chain issues."

   Why it's better: The good prompt provides a concrete example of the desired style and tone, giving Claude a clear reference point for the new email.

### 3. Encourage thinking
   - For complex tasks, ask Claude to "think step-by-step" or "explain your reasoning."
   - This can lead to more accurate and detailed responses.

   Bad prompt:
   "How can I improve team productivity?"

   Good prompt:
   "I'm looking to improve my team's productivity. Think through this step-by-step, considering the following factors:
   1. Current productivity blockers (e.g., too many meetings, unclear priorities)
   2. Potential solutions (e.g., time management techniques, project management tools)
   3. Implementation challenges
   4. Methods to measure improvement

   For each step, please provide a brief explanation of your reasoning. Then summarize your ideas at the end."

   Why it's better: The good prompt asks Claude to think through the problem systematically, providing a guided structure for the response and asking for explanations of the reasoning process.

### 4. Iterative refinement
   - If Claude's first response isn't quite right, ask for clarifications or modifications.
   - You can always say "That's close, but can you adjust X to be more like Y?"

   Bad prompt:
   "Make it better."

   Good prompt:
   "That's a good start, but please refine it further. Make the following adjustments:
   1. Make the tone more casual and friendly
   2. Add a specific example of how our product has helped a customer
   3. Shorten the second paragraph to focus more on the benefits rather than the features"

   Why it's better: The good prompt provides specific feedback and clear instructions for improvements, allowing Claude to make targeted adjustments.

### 5. Leverage Claude's knowledge
   - Claude has broad knowledge across many fields. Don't hesitate to ask for explanations or background information.
   - Be sure to include relevant context and details so that Claude's response is maximally targeted to be helpful.

   Bad prompt:
   "What is marketing? How do I do it?"

   Good prompt:
   "I'm developing a marketing strategy for a new eco-friendly cleaning product line. Can you provide an overview of current trends in green marketing? Please include:
   1. Key messaging strategies that resonate with environmentally conscious consumers
   2. Effective channels for reaching this audience
   3. Examples of successful green marketing campaigns from the past year
   4. Potential pitfalls to avoid (e.g., greenwashing accusations)

   This information will help me shape our marketing approach."

   Why it's better: The good prompt asks for specific, contextually relevant information that leverages Claude's broad knowledge base.

### 6. Use role-playing
   - Ask Claude to adopt a specific role or perspective when responding.

   Bad prompt:
   "Help me prepare for a negotiation."

   Good prompt:
   "You are a fabric supplier for my backpack manufacturing company. I'm preparing for a negotiation with this supplier to reduce prices by 10%. As the supplier, please provide:
   1. Three potential objections to our request for a price reduction
   2. For each objection, suggest a counterargument from my perspective
   3. Two alternative proposals the supplier might offer instead of a straight price cut

   Then, switch roles and provide advice on how I, as the buyer, can best approach this negotiation to achieve our goal."

   Why it's better: This prompt uses role-playing to explore multiple perspectives of the negotiation, providing more comprehensive preparation.

## Task-specific tips and examples

### Content Creation

1. **Specify your audience** — Tell Claude who the content is for.

2. **Define the tone and style** — Describe the desired tone. If you have a style guide, mention key points from it.

3. **Define output structure** — Provide a basic outline or list of points you want covered.

### Document summary and Q&A

1. **Be specific about what you want** — Ask for a summary of specific aspects or sections.
2. **Use the document names** — Refer to attached documents by name.
3. **Ask for citations** — Request that Claude cites specific parts of the document in its answers.

### Data analysis and visualization

1. **Specify the desired format** — Clearly describe the format you want the data in.

### Brainstorming

1. Use Claude to generate ideas by asking for a list of possibilities or alternatives.
2. Request responses in specific formats like bullet points, numbered lists, or tables for easier reading.

## Troubleshooting and minimizing hallucinations

1. **Allow Claude to acknowledge uncertainty** — Tell Claude it's okay to say it doesn't know.
2. **Break down complex tasks** — Work through large tasks step by step, one message at a time.
3. **Include all contextual information** — Claude doesn't retain information from previous conversations, so include all necessary context each time.`;

export default function PromptingGuideEditor() {
  const [content, setContent] = useState(initialContent);
  const [saved, setSaved] = useState(false);
  const textareaRef = useRef(null);

  const handleChange = (e) => {
    setContent(e.target.value);
    setSaved(false);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "claude-prompting-guide.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const wordCount = content.trim().split(/\s+/).filter(Boolean).length;
  const lineCount = content.split("\n").length;

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", height: "100vh", display: "flex", flexDirection: "column", background: "#f8f8f8" }}>
      {/* Toolbar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 16px", background: "#fff", borderBottom: "1px solid #e0e0e0",
        flexShrink: 0
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#333" }}>📝 claude-prompting-guide.md</span>
          <span style={{ fontSize: 11, color: "#aaa", background: "#f0f0f0", borderRadius: 4, padding: "2px 6px" }}>Markdown</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "#999" }}>{wordCount} words · {lineCount} lines</span>
          <button onClick={handleCopy} style={{
            fontSize: 12, padding: "5px 12px", borderRadius: 6, border: "1px solid #ddd",
            background: saved ? "#d4edda" : "#fff", color: saved ? "#155724" : "#444",
            cursor: "pointer", transition: "all 0.2s"
          }}>
            {saved ? "✓ Copied!" : "Copy"}
          </button>
          <button onClick={handleDownload} style={{
            fontSize: 12, padding: "5px 12px", borderRadius: 6, border: "none",
            background: "#4a4af4", color: "#fff", cursor: "pointer", fontWeight: 500
          }}>
            ↓ Download
          </button>
        </div>
      </div>

      {/* Editor */}
      <textarea
        ref={textareaRef}
        value={content}
        onChange={handleChange}
        spellCheck={false}
        style={{
          flex: 1,
          width: "100%",
          padding: "24px 32px",
          fontSize: 13.5,
          lineHeight: 1.75,
          fontFamily: "'Fira Mono', 'Courier New', monospace",
          color: "#222",
          background: "#fff",
          border: "none",
          outline: "none",
          resize: "none",
          boxSizing: "border-box",
          overflowY: "auto",
          tabSize: 2,
        }}
      />
    </div>
  );
}