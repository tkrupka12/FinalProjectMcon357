"""
Business Logic and AI Integration
Following the flow diagram for conversation processing

AGENT ARCHITECTURE (Advanced Multi-Prompt System):
1. PERCEPTION LAYER: extract_information_from_message()
   - Uses a specialized prompt to parse natural language into structured JSON data.
   
2. REASONING LAYER: determine_follow_up_questions()
   - Uses a decision-making prompt to identify information gaps and formulate targeted questions.
   
3. GENERATION LAYER: generate_lesson_plan_with_ai()
   - Uses a synthesis prompt with context injection to create the final artifact.
   
4. ORCHESTRATION: process_conversation()
   - Implements a custom State Machine (Grade -> Context -> Questions -> Generation) to manage the multi-turn agent workflow.
"""
import json
import logging
import re
from openai import OpenAI
from config import OPENAI_API_KEY

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Constants & Configuration ---
class ConversationState:
    GRADE_LEVEL = 'grade_level'
    COLLECTING_BASIC = 'collecting_basic'
    BATCH_FOLLOW_UP = 'batch_follow_up'
    GENERATE_LESSON = 'generate_lesson'
    ASK_FOR_MODIFICATIONS = 'ask_for_modifications'

# Keyword lists for intent detection
KEYWORDS_GENERATE_NOW = ['generate', 'draft', 'now', 'skip', 'create', 'make']
KEYWORDS_DONT_KNOW = ["don't know", "dont know", "not sure", "what is this", "help"]
KEYWORDS_CANT_SEE_PLAN = ["don't see", "dont see", "can't see", "cant see", "not seeing", "where is", "show me", "i don't see", "i dont see", "lesson", "plan"]
KEYWORDS_SATISFACTION = ['no', 'good', 'great', 'perfect', 'thanks', 'thank', 'love', 'awesome', 'happy', 'like it']
KEYWORDS_MALICIOUS = ['trick', 'hack', 'stupid', 'ignore', 'fail']

# Keywords that trigger a modification to an existing plan
KEYWORDS_MODIFICATION = [
    'yes', 'change', 'modify', 'add', 'update', 'edit', 'different', 'more', 'also', 
    'provide', 'picture', 'image', 'photo', 
    'not', 'wrong', 'incorrect', 'error', 'mistake', 'accurate'
]

# Keywords that trigger a worksheet generation
KEYWORDS_WORKSHEET = ['worksheet', 'work sheet', 'activity sheet', 'exercises', 'problems', 'quiz', 'test', 'assessment', 'homework', 'practice page']
# Keywords that imply a multi-lesson unit plan
KEYWORDS_UNIT_PLAN = ['unit', 'unit plan', 'unit planner', 'week plan', '2 week plan', 'multi-day', 'multi lesson', 'multi-lesson', 'sequence of lessons', 'series of lessons', 'scope and sequence']


# --- AI Helper Functions ---

def extract_information_from_message(message, current_state=None):
    """
    Uses AI to extract structured information from user messages
    """
    try:
        # Prompt designed to extract educational context
        prompt = f"""
        Extract educational information from the following user message.
        IMPORTANT: If the user provides a Topic (e.g. "Fractions", "Weather") but no Subject, you MUST INFER the Subject (e.g. "Math", "Science").
        If you cannot infer a standard subject, use the Topic as the Subject.
        
        Return ONLY a JSON object with these keys (value should be null if not found):
        - grade_level
        - subject (Infer this if Topic is known)
        - topic
        - duration
        - objectives
        - standards (e.g., CCSS.MATH.CONTENT.4.NF.B.3, TEKS 5.3A)
        - class_size
        - learning_style (visual, auditory, kinesthetic, etc.)
        - special_needs (any mentioned accommodations)
        - resources (available materials)
        - sentiment (positive, negative, neutral)
        - intent (create_lesson, modify_lesson, create_worksheet, create_unit_plan, answer_question, chitchat)
        - key_concepts (any specific keywords, themes, or non-standard requests)
        - unit_length (e.g., "1 week", "5 lessons", "10 days")

        User Message: "{message}"
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts structured data from text. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.error(f"Error extracting information: {str(e)}")
        return {}

def determine_follow_up_questions(data):
    """
    Determine relevant follow-up questions based on missing information
    Returns a dict with 'message' and 'options' (checkbox-friendly)
    """
    try:
        # Only ask questions if we're missing critical info or want to deepen context
        required_fields = ['grade_level', 'subject', 'topic']
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            # We need these basics first
            return None 

        # Build checkbox-friendly options (static but contextualized)
        grade = data.get('grade_level', 'this grade')
        subject = data.get('subject', 'this subject')
        topic = data.get('topic', 'this topic')
        plan_type = data.get('plan_type', 'single lesson')

        options = [
            f"Align to specific standards (e.g., CCSS/TEKS) for {grade} {subject}",
            f"Include a hands-on or worksheet activity for {topic}",
            "Set a time constraint (e.g., 45 minutes) and pacing",
            "Add differentiation for struggling/advanced learners",
            "Add an exit ticket or quick formative check",
        ]

        # Unit-specific option
        if plan_type == 'unit':
            options.insert(1, "Create a multi-lesson sequence (5–10 lessons) with progression")

        message = (
            f"I'm drafting your {plan_type.replace('_', ' ')} on {topic} now. "
            f"When the plan appears, you'll get optional additions tailored to it. "
            f"If you have requests already, type them here and I'll bake them in."
        )

        return {
            'message': message,
            'options': options
        }
    except Exception as e:
        logger.error(f"Error generating follow-up questions: {str(e)}")
        # Fallback
        return {
            'message': "To make this lesson perfect, select any of these options (or just click Submit/Generate now):",
            'options': [
                "Align to standards (CCSS/TEKS)",
                "Add a worksheet/hands-on activity",
                "Set a time constraint",
                "Add differentiation",
                "Add an exit ticket"
            ]
        }

def build_optional_additions(data):
    """
    Build topic-specific optional additions that attach to the generated lesson plan
    """
    try:
        grade = data.get('grade_level') or 'this grade'
        subject = data.get('subject') or 'this subject'
        topic = data.get('topic') or 'this topic'
        plan_type = data.get('plan_type') or 'lesson'
        learning_style = data.get('learning_style')

        base_options = [
            f"Align to {grade} {subject} standards for {topic} (CCSS/TEKS where relevant)",
            f"Add topic-specific practice for {topic} with an answer key",
            "Embed quick formative checks every 10–15 minutes",
            "Add differentiation moves for struggling and advanced students",
            f"Create a concise exit ticket focused on {topic}"
        ]

def grade_difficulty_requirements(grade_level):
    """
    Return grade-band specific rigor guidance for worksheets
    """
    try:
        grade_text = (grade_level or '').lower()
        # Numeric extraction fallback
        num_match = re.search(r'(\d+)', grade_text)
        num_grade = int(num_match.group(1)) if num_match else None

        # Determine band
        if 'pre' in grade_text or 'kinder' in grade_text or (num_grade is not None and num_grade <= 2):
            return (
                "K-2: keep passages very short (1-2 sentences), use picture cues, "
                "ask 3 literal questions with one-word answers, and 1 simple 'why' question."
            )
        if (num_grade is not None and 3 <= num_grade <= 5) or any(g in grade_text for g in ['3rd', '4th', '5th']):
            return (
                "3-5: include a 100-140 word passage, 5-6 questions with a mix of "
                "literal, vocabulary-in-context, and one inference question; include one short constructed response."
            )
        if (num_grade is not None and 6 <= num_grade <= 8) or any(g in grade_text for g in ['6th', '7th', '8th', 'middle']):
            return (
                "6-8: include a 150-220 word passage with grade-appropriate complexity; "
                "provide 6-8 questions: at least 2 inference, 1 author-purpose/tone, "
                "1 vocabulary-in-context, and 1 short constructed response that requires citing textual evidence."
            )
        if (num_grade is not None and num_grade >= 9) or any(g in grade_text for g in ['9th', '10th', '11th', '12th', 'high']):
            return (
                "9-12: include a 200-300 word complex passage; provide 8-10 questions: "
                "evidence-based analysis, rhetorical purpose, tone, vocabulary-in-context, "
                "and 2 short constructed responses requiring cited textual evidence and synthesis."
            )
        # Default if grade not recognized
        return (
            "Use a passage and questions that match the stated grade; include inference, "
            "vocabulary-in-context, and at least one evidence-citing short response."
        )
    except Exception as e:
        logger.error(f"Error building difficulty requirements: {str(e)}")
        return (
            "Use grade-appropriate rigor with inference and evidence-based questions plus a short response."
        )

        # Unit-specific enrichment
        if plan_type == 'unit':
            base_options.insert(2, f"Add a project-based arc that threads {topic} across the unit")

        # Subject-tailored options
        subject_lower = subject.lower()
        if 'math' in subject_lower:
            base_options.append(f"Include 5 extra {topic} problems with step-by-step solutions")
        elif 'science' in subject_lower:
            base_options.append(f"Add a mini lab/demo for {topic} with materials and safety notes")
        elif any(key in subject_lower for key in ['ela', 'english', 'reading', 'literature']):
            base_options.append(f"Add a short text excerpt plus discussion prompts for {topic}")
        elif any(key in subject_lower for key in ['history', 'social studies', 'civics']):
            base_options.append(f"Link {topic} to a primary source and a current event comparison")

        if learning_style:
            base_options.append(f"Include a {learning_style} friendly activity tailored to {topic}")

        # Remove duplicates while preserving order
        seen = set()
        options = []
        for opt in base_options:
            if opt and opt not in seen:
                seen.add(opt)
                options.append(opt)

        return options
    except Exception as e:
        logger.error(f"Error building optional additions: {str(e)}")
        return [
            "Align to standards",
            "Add more practice problems",
            "Add differentiation strategies",
            "Add an exit ticket"
        ]

def generate_lesson_plan_with_ai(data):
    """
    Generate a comprehensive lesson plan using AI
    Following the flow diagram for lesson plan generation
    """
    try:
        # Build additional context
        additional_notes = ""
        if data.get('engagement'):
            additional_notes += f"\nENGAGEMENT REQUIREMENTS: {data.get('engagement')}"
        if data.get('difficulty'):
            additional_notes += f"\nDIFFICULTY LEVEL: {data.get('difficulty')}"
        if data.get('modification_notes'):
            additional_notes += f"\nUSER MODIFICATION REQUEST: {data.get('modification_notes')}\nIMPORTANT: The user wants to modify the previous plan. Please pay special attention to this request."

        # Ensure duration is never blank; default to 45 minutes if missing
        duration_value = data.get('duration') or '45 minutes'
        
        prompt = f"""
        Create a clear, concise lesson plan a busy teacher can read quickly and deliver with confidence. Use short sentences, plain language, and keep every section actionable. Make the topic obvious at the top and ensure every section is easy to skim.

        CRITICAL INSTRUCTIONS - MANDATORY CONTENT RULES:
        1. STRICT GRADE LEVEL ADHERENCE & COMPLEXITY SCALING:
           - Adjust complexity, language, and examples to match {data.get('grade_level', 'Not specified')}.
           - **PROGRESSIVE DIFFICULTY:** As the grade level increases, the lesson plan MUST become significantly more complex and rigorous.
             - **Pre-K to 2nd:** Focus on foundational skills, concrete examples, play-based learning, and very simple language. Use visual aids heavily.
             - **3rd to 5th:** Introduce more structured activities, independent work, and slightly more abstract concepts.
             - **6th to 8th:** Require critical thinking, analysis, and multi-step problem solving. Use complex real-world contexts (economics, current events, scientific data). NO childish examples.
             - **9th to 12th:** DEMAND high-level synthesis, evaluation, and creation. rigorous academic language, primary source analysis, and college-prep level tasks.
           - ALWAYS check the user's profile Grade/Subject. If the user says "7th Grade", do NOT generate 3rd-grade content.
        2. NO GENERIC PLACEHOLDERS: You are STRICTLY FORBIDDEN from using phrases like "[Insert example here]", "[Select a text]", or "[Discuss news]".
        3. CONCRETE, SPECIFIC CONTENT ("DETAIL") REQUIRED:
           - MATH: Provide 5 SPECIFIC problems (e.g., "$12.45 + 3.20") and word problems.
           - TEACHER SCRIPT: Provide exact dialogue for explaining the concept.
           - MISCONCEPTIONS: List specific student errors (e.g., "Students might forget to align the decimal point").
           - SOCIAL STUDIES/CURRENT EVENTS: Provide 3 SPECIFIC, real-world events/headlines from the current year.
           - SCIENCE: Provide a SPECIFIC experiment description with a list of REAL materials.
           - ELA: Provide a SPECIFIC excerpt or a list of 3-5 actual vocabulary words relevant to the grade.
        4. VISUAL/STRUCTURAL MODELING:
           - Include a 'Visual Aid' section. For Math/Science, show EXACTLY how the numbers/diagrams should look on the board (e.g., vertical alignment of decimals).

        GRADE LEVEL: {data.get('grade_level', 'Not specified')}
        SUBJECT: {data.get('subject', 'Not specified')}
        TOPIC: {data.get('topic', 'Not specified')}
        DURATION: {duration_value}
        LEARNING OBJECTIVES: {data.get('objectives', 'Not specified')}
        STANDARDS TO ALIGN: {data.get('standards', 'Not specified')}
        CLASS SIZE: {data.get('class_size', 'Not specified')}
        LEARNING STYLE: {data.get('learning_style', 'Not specified')}
        SPECIAL NEEDS: {data.get('special_needs', 'Not specified')}
        AVAILABLE RESOURCES: {data.get('resources', 'Not specified')}
        KEY CONCEPTS/REQUESTS: {data.get('key_concepts', 'Not specified')}
        {additional_notes}

        FORMAT STRICTLY IN HTML (NO MARKDOWN, NO CODE BLOCKS).
        Use the class names below so it renders with the app's green-header lesson plan styling.
        Return ONLY valid HTML (no ``` fences).

        Required HTML structure:
        <div class="lesson-header">
          <h2>📋 LESSON PLAN: [TOPIC]</h2>
          <div class="quick-info">
            <p><strong>Grade:</strong> [GRADE] | <strong>Subject:</strong> [SUBJECT] | <strong>Duration:</strong> [TIME]</p>
          </div>
        </div>

        <div class="lesson-section">
          <h3>🎯 Learning Objectives</h3>
          <ul>
            <li>...</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3>📦 Materials & Prep</h3>
          <ul>
            <li><strong>Materials:</strong> ...</li>
            <li><strong>Prep Time:</strong> ...</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3>👀 Visual Aid / Board Work</h3>
          <p><em>(Describe exactly what to draw/write on the board to model this concept visually. For Math, show the vertical alignment or algorithm step-by-step.)</em></p>
          <div style="border: 2px dashed #ccc; padding: 15px; background: #f9f9f9; font-family: 'Courier New', monospace; white-space: pre;">
            <!-- content here (e.g. ASCII art or structured text showing the math layout) -->
          </div>
        </div>

        <div class="lesson-section">
          <h3>⏱️ Lesson Timeline</h3>
          <ol>
            <li><strong>[X] min</strong> [Activity] — [What to do]</li>
          </ol>
        </div>

        <div class="lesson-section">
          <h3>📝 Step-by-Step Instructions</h3>
          <h4>Opening ([X] minutes)</h4>
          <ol>
            <li><strong>Hook/Engagement:</strong> [Age-appropriate hook. For 6th+, use real-world data/money/sports. For K-5, use games/stories.]</li>
            <li><strong>Activate Prior Knowledge:</strong> [steps]</li>
            <li><strong>Introduce Objectives:</strong> [steps]</li>
          </ol>
          <h4>Main Activities ([X] minutes)</h4>
          <ol>
            <li><strong>[Activity 1 Name]</strong>
              <ul>
                <li>Steps: ...</li>
                <li><em>Teacher Script:</em> "[Exact words to explain the concept using a real-world example]"</li>
                <li><em>Visual Model:</em> [How to demonstrate this step]</li>
                <li><em>Students do:</em> [expected actions]</li>
                <li><em>Check for Understanding:</em> [Specific question to ask]</li>
              </ul>
            </li>
            <li><strong>[Activity 2 Name]</strong>
              <ul>
                 <li>Steps: ...</li>
                 <li><em>Teacher Script:</em> "[Exact words]"</li>
                 <li><em>Specific Content:</em> [Insert specific problems/text/experiment details here]</li>
                 <li><em>Students do:</em> [expected actions]</li>
              </ul>
            </li>
          </ol>
          <h4>Closing ([X] minutes)</h4>
          <ul>
            <li><strong>Review:</strong> [specific activity]</li>
            <li><strong>Quick Check:</strong> [1-2 minute check]</li>
            <li><strong>Preview Next Lesson:</strong> [what to tell students]</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3 data-section="assessment">✅ Assessment & Checks</h3>
          <ul>
            <li><strong>Formative (During):</strong> [Specific questions/checks]</li>
            <li><strong>Summative (End):</strong> [Exit ticket with specific problems]</li>
            <li><strong>Common Misconceptions:</strong> [Specific student errors to anticipate (e.g. decimal alignment) and how to address them]</li>
            <li><strong>Success criteria:</strong> [what “good” looks like]</li>
          </ul>
        </div>

        <div class="lesson-section">
           <h3 data-section="content-resources">📚 Specific Content Resources</h3>
           <div style="background: #eef7fa; padding: 15px; border-left: 4px solid #3498db;">
             <p><strong>Use these exact items in the lesson:</strong></p>
             <!-- IF MATH: Provide 5 problems + Answer Key -->
             <!-- IF ELA: Provide excerpt/vocab list -->
             <!-- IF SCIENCE: Provide experiment details -->
             <!-- IF SOCIAL STUDIES: Provide 3 real events -->
           </div>
        </div>

        <div class="lesson-section">
          <h3>🎓 Differentiation</h3>
          <ul>
            <li><strong>Struggling:</strong> ...</li>
            <li><strong>Advanced:</strong> ...</li>
            <li><strong>Special Needs:</strong> ...</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3 data-section="tips">💡 Tips & Pitfalls</h3>
          <ul>
            <li><strong>Pro Tip:</strong> ...</li>
            <li><strong>Watch Out:</strong> ...</li>
            <li><strong>If Students Struggle:</strong> ...</li>
            <li><strong>Time Management:</strong> ...</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3>📚 Extensions & Homework</h3>
          <ul><li>...</li></ul>
        </div>

        <div class="lesson-section">
          <h3>🤔 Reflection Questions</h3>
          <ul><li>...</li></ul>
        </div>

        IMPORTANT:
        - Output MUST be pure HTML (no markdown, no code fences).
        - Be SPECIFIC and ACTIONABLE with exact words teachers can say.
        - Provide explicit time allocations where relevant.
        - Keep it concise, skimmable, and classroom-ready.
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert educational consultant and curriculum designer with 20+ years of experience. Your specialty is creating CLEAR, ACTIONABLE lesson plans that teachers can implement immediately. You write in a direct, practical style with specific step-by-step instructions."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.6
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error generating lesson plan: {str(e)}", exc_info=True)
        return f"<p>I apologize, but I encountered an error while generating your lesson plan: {str(e)}</p><p>Please try again or contact support.</p>"

def generate_worksheet(data):
    """
    Generate a student worksheet and teacher summary based on the lesson plan data
    """
    try:
        difficulty_notes = grade_difficulty_requirements(data.get('grade_level', 'Grade'))
        prompt = f"""
        Create a student worksheet and a brief bulleted lesson summary for the teacher based on this lesson:
        
        TOPIC: {data.get('topic', 'Topic')}
        GRADE: {data.get('grade_level', 'Grade')}
        SUBJECT: {data.get('subject', 'Subject')}
        OBJECTIVES: {data.get('objectives', 'Standard Objectives')}
        
        DIFFICULTY REQUIREMENTS (grade-specific):
        {difficulty_notes}
        
        The output should be in HTML format and include:
        1. A "Teacher's Quick Summary" (3-5 bullet points of key takeaways).
        2. A "Student Worksheet" section that can be printed/copied.
           - Follow the difficulty requirements above for passage length, rigor, and number/type of questions.
           - For grades 6-8+, require evidence-based answers where appropriate.
           - Include an answer key at the very bottom with concise, specific answers (no placeholders).
           
        Format:
        <div class="worksheet-container" style="background: white; padding: 20px; border-radius: 10px; border: 1px solid #ddd; margin-top: 20px;">
            <div class="teacher-summary" style="margin-bottom: 30px;">
                <h3 style="color: #2c3e50;">👩‍🏫 Teacher's Quick Summary</h3>
                <ul style="background: #f8f9fa; padding: 15px 30px; border-radius: 8px;">
                    <!-- Insert 3-5 summary bullets here -->
                </ul>
            </div>
            <hr style="border: 0; border-top: 2px dashed #ccc; margin: 30px 0;">
            <div class="student-worksheet">
                <h3 style="text-align: center; color: #2c3e50;">📝 Student Worksheet: {data.get('topic', 'Lesson')}</h3>
                <div style="display: flex; justify-content: space-between; margin-bottom: 20px;">
                    <p><strong>Name:</strong> ____________________</p>
                    <p><strong>Date:</strong> ____________________</p>
                </div>
                
                <!-- Insert questions/activities here -->
                
            </div>
            <div class="answer-key" style="margin-top: 40px; border-top: 1px solid #eee; padding-top: 20px; font-size: 0.9em; color: #666;">
                <h4>🔑 Answer Key (Teacher Only)</h4>
                <!-- Insert answers here -->
            </div>
        </div>
        """
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a teacher creating classroom resources."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating worksheet: {str(e)}")
        return "<p>Sorry, I couldn't generate the worksheet at this time.</p>"

def generate_unit_plan_with_ai(data):
    """
    Generate a multi-lesson unit plan (sequence of lessons)
    """
    try:
        unit_length = data.get('unit_length') or '1 week (5 lessons)'
        standards = data.get('standards', 'Not specified')
        prompt = f"""
        Create a concise UNIT PLAN consisting of 5–10 connected lessons (default 5 if not specified) for the topic below.
        Make the plan skimmable, with each lesson clearly numbered and timeboxed.
        REQUIREMENTS:
        - Grade: {data.get('grade_level', 'Not specified')}
        - Subject: {data.get('subject', 'Not specified')}
        - Topic/Focus: {data.get('topic', 'Not specified')}
        - Unit Length: {unit_length} (assume 5 lessons if unclear)
        - Standards to align: {standards}
        - Objectives: {data.get('objectives', 'Not specified')}
        - Special Needs: {data.get('special_needs', 'Not specified')}
        
        OUTPUT FORMAT (HTML, no code fences):
        <div class="lesson-header">
          <h2>📋 UNIT PLAN: [TOPIC]</h2>
          <div class="quick-info">
            <p><strong>Grade:</strong> [GRADE] | <strong>Subject:</strong> [SUBJECT] | <strong>Standards:</strong> [STANDARDS] | <strong>Length:</strong> [UNIT LENGTH]</p>
          </div>
        </div>

        <div class="lesson-section">
          <h3>🎯 Unit Outcomes</h3>
          <ul>
            <li>3-5 clear, measurable outcomes aligned to the standards.</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3>📆 Lesson Sequence</h3>
          <ol>
            <li><strong>Lesson 1 Title (Day 1):</strong> Goal, key activity, assessment, materials.</li>
            <li><strong>Lesson 2 Title (Day 2):</strong> Goal, key activity, assessment, materials.</li>
            <li><strong>Lesson 3 Title (Day 3):</strong> ...</li>
            <li><strong>Lesson 4 Title (Day 4):</strong> ...</li>
            <li><strong>Lesson 5 Title (Day 5):</strong> ...</li>
            <!-- If unit_length implies more than 5, add up to 10 lessons total -->
          </ol>
        </div>

        <div class="lesson-section">
          <h3>✅ Assessments & Evidence</h3>
          <ul>
            <li>Formative checks per lesson.</li>
            <li>Summative/end-of-unit assessment idea.</li>
            <li>Success criteria aligned to standards.</li>
          </ul>
        </div>

        <div class="lesson-section">
          <h3>🎓 Differentiation & Supports</h3>
          <ul>
            <li>Struggling learners accommodations.</li>
            <li>Advanced extensions.</li>
            <li>Special needs / ELL supports.</li>
          </ul>
        </div>

        IMPORTANT:
        - Be specific and actionable; include concrete activities.
        - Ensure rigor scales with grade level.
        - Keep HTML only (no markdown/code fences).
        """
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert curriculum designer who creates concise, standards-aligned unit plans."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.65
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating unit plan: {str(e)}", exc_info=True)
        return f"<p>Sorry, I couldn't generate the unit plan: {str(e)}</p>"

# --- Main Logic ---

def process_conversation(user_message, state):
    """
    Main logic for processing the conversation state
    Returns dict with message, new_state, and optional lessonPlan
    """
    step = state.get('step', ConversationState.GRADE_LEVEL)
    data = state.get('data', {})
    user_profile = state.get('user_profile', {}) or {}

    # If onboarding already has a grade level, use it automatically even if state resets
    if step == ConversationState.GRADE_LEVEL and not data.get('grade_level'):
        saved_grade = user_profile.get('grade_level')
        if saved_grade and str(saved_grade).strip() and saved_grade != 'NOT SET':
            data['grade_level'] = str(saved_grade).strip()
            state['data'] = data
    
    # Extract info using AI
    extracted = extract_information_from_message(user_message, step)
    
    # Update data with any new info found
    # Only update if value is not null/empty
    for key, value in extracted.items():
        if value and value != 'null':
            # Handle strings
            if isinstance(value, str) and value.strip():
                # Don't overwrite existing valid data with vague new data unless specific
                if key not in data or value != 'Not specified':
                    data[key] = value.strip()
            # Handle lists/other types (sometimes AI returns lists for resources etc)
            elif not isinstance(value, str):
                data[key] = value

    # Plan type detection (unit vs single lesson)
    is_unit_request = extracted.get('intent') == 'create_unit_plan' or any(
        phrase in user_message.lower() for phrase in KEYWORDS_UNIT_PLAN
    )
    if is_unit_request:
        data['plan_type'] = 'unit'
        if not data.get('unit_length'):
            data['unit_length'] = extracted.get('unit_length') or '1 week (5 lessons)'
    else:
        if not data.get('plan_type'):
            data['plan_type'] = 'single_lesson'
    
    # State Machine Logic
    
        # GLOBAL SECURITY CHECK: Check for malicious intent or "tricks"
    if extracted.get('intent') == 'chitchat' or extracted.get('sentiment') == 'negative':
         # If the AI detects weird input, handle it gracefully but firmly
         if any(phrase in user_message.lower() for phrase in KEYWORDS_MALICIOUS):
             return {
                'success': True,
                'state': state,
                'message': "I'm here to help you create lesson plans! Let's get back on track. What part of the lesson would you like to work on?"
            }
         # If the user is just saying "history" or "math", it might be misclassified as chitchat
         # Only block if we really don't have a valid subject yet
         if not data.get('subject') and not extracted.get('subject'):
             pass # Let it fall through to normal logic
         elif extracted.get('intent') == 'chitchat' and not any(k in user_message.lower() for k in ['hi', 'hello', 'hey']):
             pass # Let it fall through, it might be a subject name

    # GLOBAL INTENT CHECK: Create Worksheet
    # Prioritize worksheet generation if explicitly requested, reusing context
    is_worksheet_request = (
        extracted.get('intent') == 'create_worksheet' or 
        any(phrase in user_message.lower() for phrase in KEYWORDS_WORKSHEET)
    )
    
    if is_worksheet_request:
        # Try to resolve context from data, profile, or extraction
        current_grade = data.get('grade_level') or user_profile.get('grade_level') or extracted.get('grade_level')
        current_topic = data.get('topic') or extracted.get('topic')
        current_subject = data.get('subject') or extracted.get('subject')
        
        # If we have at least Topic and Grade, we can generate a worksheet
        if current_topic and current_grade:
             # Ensure data has these values for the generator
             data['grade_level'] = current_grade
             data['topic'] = current_topic
             if current_subject: data['subject'] = current_subject
             state['data'] = data
             
             worksheet_content = generate_worksheet(data)
             state['step'] = ConversationState.ASK_FOR_MODIFICATIONS
             
             return {
                'success': True,
                'state': state,
                'message': f"I've created a worksheet for your <strong>{current_grade}</strong> lesson on <strong>{current_topic}</strong>:\n\n{worksheet_content}\n\nWould you like any changes to this worksheet?"
             }
        elif step == ConversationState.ASK_FOR_MODIFICATIONS and data.get('topic'):
             # If we are in modification state but somehow missed the check above (maybe grade missing?)
             # We likely have enough context in 'data' even if local vars failed
             worksheet_content = generate_worksheet(data)
             return {
                'success': True,
                'state': state,
                'message': f"I've created a worksheet for your lesson:\n\n{worksheet_content}\n\nWould you like any changes?"
             }
        else:
             # If missing context, ask for it but stay in flow if possible
             return {
                 'success': True,
                 'state': state,
                 'message': "I'd love to make a worksheet! Could you confirm the topic and grade level you'd like it for?"
             }

    # RECOVERY LOGIC: If step is GRADE_LEVEL but user is asking for modifications, try to recover
    # This handles cases where state might be lost on the client side
    if step == ConversationState.GRADE_LEVEL and any(phrase in user_message.lower() for phrase in ['depth', 'detail', 'picture', 'image', 'photo', 'more', 'change', 'add', 'make it']):
        # If we have basic data, assume we are in modification mode
        if data.get('grade_level') and data.get('subject'):
             logger.info("Recovering lost state: transitioning to ASK_FOR_MODIFICATIONS based on user intent")
             step = ConversationState.ASK_FOR_MODIFICATIONS
             state['step'] = step

    if step == ConversationState.GRADE_LEVEL:
        # Check if we got the grade level from onboarding/profile
        user_profile = state.get('user_profile', {})
        if user_profile and user_profile.get('grade_level'):
            data['grade_level'] = user_profile.get('grade_level')
            state['data'] = data
            state['step'] = ConversationState.COLLECTING_BASIC
            return {
                'success': True,
                'state': state,
                'message': f"I see you teach {data['grade_level']}. What subject would you like to create a lesson plan for?"
            }
            
        # Check if we got the grade level from message
        if data.get('grade_level'):
            # Move to next step
            state['step'] = ConversationState.COLLECTING_BASIC
            return {
                'success': True,
                'state': state,
                'message': "Great! What subject are you teaching?"
            }
        else:
            # Still need grade level
            return {
                'success': True,
                'state': state,
                'message': "I'd love to help you with your lesson plan! To start, what grade level do you teach?"
            }
            
    elif step == ConversationState.COLLECTING_BASIC:
        # Check if we have subject and topic
        if not data.get('subject'):
            # Fallback for loop prevention:
            # If we are asking for a subject and the user replies with something that extraction didn't catch as a subject,
            # (e.g., "weatheroutside" which might be seen as a topic or gibberish), use the raw input as the subject to proceed.
            if user_message and str(user_message).strip() and not any(k in user_message.lower() for k in KEYWORDS_DONT_KNOW + KEYWORDS_GENERATE_NOW):
                 if not extracted.get('subject'):
                     logger.info(f"Fallback: Using user message '{user_message}' as subject since extraction failed.")
                     data['subject'] = user_message.strip().title()
            
            # Re-check after fallback
            if not data.get('subject'):
                return {
                    'success': True,
                    'state': state,
                    'message': "Got it. What subject is this for?"
                }
        
        if not data.get('topic'):
            # If we extracted a topic from this message, great. If not, ask.
            # But sometimes subject and topic come together "Math lesson on fractions"
            # SPECIAL CASE: If subject is present but topic is missing, assume the user JUST gave the subject
            # and we need to ask for the topic next.
            if extracted.get('topic') and extracted['topic'] != data['subject']:
                 data['topic'] = extracted['topic']
            else:
                return {
                    'success': True,
                    'state': state,
                    'message': f"Okay, {data['grade_level']} {data['subject']}. What specific topic would you like to cover?"
                }
        
        # We have Grade, Subject, Topic. 
        # SWITCH TO BATCH STRATEGY: Generate multiple questions at once
        questions_data = determine_follow_up_questions(data)
        
        state['step'] = ConversationState.BATCH_FOLLOW_UP
        if isinstance(questions_data, dict):
            return {
                'success': True,
                'state': state,
                'message': questions_data.get('message', '')
            }
        else:
            return {
                'success': True,
                'state': state,
                'message': questions_data
            }
        
    elif step == ConversationState.BATCH_FOLLOW_UP:
        # The user has answered the batch questions (or said "generate")
        # Store their response as context
        if user_message and not any(k in user_message.lower() for k in KEYWORDS_GENERATE_NOW):
             # Append to key_concepts so the generator sees it
             current_concepts = data.get('key_concepts', '')
             data['key_concepts'] = f"{current_concepts} {user_message}".strip()
        
        # Generate the plan immediately (unit or single)
        if data.get('plan_type') == 'unit':
            lesson_plan = generate_unit_plan_with_ai(data)
            success_msg = "Your unit plan is ready! Let me know if you'd like to make any changes."
        else:
            lesson_plan = generate_lesson_plan_with_ai(data)
            success_msg = "Your lesson plan is ready! Let me know if you'd like to make any changes. If you're happy with it, is there anything else you'd like help with, or would you like to create another lesson plan?"

        state['step'] = ConversationState.ASK_FOR_MODIFICATIONS
        
        return {
            'success': True,
            'state': state,
            'message': success_msg,
            'lessonPlan': lesson_plan,
            'options': build_optional_additions(data)
        }

    
    elif step == ConversationState.ASK_FOR_MODIFICATIONS:
        user_lower = user_message.lower()
        user_profile = state.get('user_profile', {})
        
        # Check if user is saying they don't see the plan - resend it
        if any(phrase in user_lower for phrase in KEYWORDS_CANT_SEE_PLAN):
            if data.get('plan_type') == 'unit':
                lesson_plan = generate_unit_plan_with_ai(data)
                return {
                    'success': True,
                    'state': state,
                    'message': "Here's your unit plan again!",
                    'lessonPlan': lesson_plan,
                    'options': build_optional_additions(data)
                }
            else:
                lesson_plan = generate_lesson_plan_with_ai(data)
                return {
                    'success': True,
                    'state': state,
                    'message': "Here's your lesson plan again!",
                    'lessonPlan': lesson_plan,
                    'options': build_optional_additions(data)
                }
            
        # CHECK FOR WORKSHEET REQUEST (Explicit context reuse)
        if any(phrase in user_lower for phrase in KEYWORDS_WORKSHEET):
            # Verify we have enough context to generate a worksheet
            if data.get('topic') and data.get('grade_level'):
                worksheet_content = generate_worksheet(data)
                return {
                    'success': True,
                    'state': state,
                    'message': f"I've created a worksheet for your <strong>{data.get('grade_level')}</strong> lesson on <strong>{data.get('topic')}</strong>:\n\n{worksheet_content}\n\nWould you like any changes to this worksheet?"
                }
            else:
                # If missing context, ask for it but stay in flow if possible
                return {
                    'success': True,
                    'state': state,
                    'message': "I'd love to make a worksheet! Could you confirm the topic and grade level you'd like it for?"
                }
        
        # Check if user is starting a new flow implicitly (provided a subject/topic)
        # This prevents the "Awesome! What next?" loop when user says "history" etc.
        extracted_intent = extract_information_from_message(user_message)
        if (extracted_intent.get('subject') or extracted_intent.get('topic')) and not any(phrase in user_lower for phrase in KEYWORDS_MODIFICATION):
            # Transition to COLLECTING_BASIC
            logger.info("Implicit new conversation detected in ASK_FOR_MODIFICATIONS")
            state['step'] = ConversationState.COLLECTING_BASIC
            
            # Keep grade level if available
            new_data = {}
            if user_profile and user_profile.get('grade_level'):
                new_data['grade_level'] = user_profile.get('grade_level')
            elif data.get('grade_level'):
                new_data['grade_level'] = data.get('grade_level')
            
            if extracted_intent.get('subject'):
                new_data['subject'] = extracted_intent['subject']
            if extracted_intent.get('topic'):
                new_data['topic'] = extracted_intent['topic']
            
            state['data'] = new_data
            
            # If we have subject but no topic, ask for topic
            if new_data.get('subject') and not new_data.get('topic'):
                return {
                    'success': True,
                    'state': state,
                    'message': f"Okay, {new_data.get('grade_level', '3rd Grade')} {new_data['subject']}. What specific topic would you like to cover?"
                }
            # If we have topic, ask follow up
            elif new_data.get('topic'):
                questions_data = determine_follow_up_questions(new_data)
                state['step'] = ConversationState.BATCH_FOLLOW_UP
                if isinstance(questions_data, dict):
                    return {
                        'success': True,
                        'state': state,
                        'message': questions_data.get('message', '')
                    }
                else:
                    return {
                        'success': True,
                        'state': state,
                        'message': questions_data
                    }
        
        # Check if user wants to make changes
        if any(phrase in user_lower for phrase in KEYWORDS_MODIFICATION):
            # User wants to make changes - extract what they want to change
            # But don't reset grade level if it's saved in user profile - use that instead
            if any(word in user_lower for word in ['grade', 'level']):
                # Only ask for grade if user explicitly wants to change it AND it's not in their profile
                if user_profile and user_profile.get('grade_level'):
                    # Use saved grade from profile
                    data['grade_level'] = user_profile.get('grade_level')
                    return {
                        'success': True,
                        'state': state,
                        'message': f"I'll use your saved grade level ({user_profile.get('grade_level')}). What else would you like to change?"
                    }
                else:
                    state['step'] = ConversationState.COLLECTING_BASIC
                    data.pop('grade_level', None)
                    return {
                        'success': True,
                        'state': state,
                        'message': "Sure! Let's update the grade level. What grade do you teach?"
                    }
            elif any(word in user_lower for word in ['subject']):
                state['step'] = ConversationState.COLLECTING_BASIC
                data.pop('subject', None)
                return {
                    'success': True,
                    'state': state,
                    'message': "Of course! What subject would you like to change it to?"
                }
            elif any(word in user_lower for word in ['topic']):
                data.pop('topic', None)
                return {
                    'success': True,
                    'state': state,
                    'message': "What topic would you like to change it to? Or what would you like to add?"
                }
            elif any(word in user_lower for word in ['objective', 'goal', 'learn']):
                data.pop('objectives', None)
                return {
                    'success': True,
                    'state': state,
                    'message': "What learning objectives would you like to add or change?"
                }
            elif any(word in user_lower for word in ['duration', 'time', 'length']):
                data.pop('duration', None)
                return {
                    'success': True,
                    'state': state,
                    'message': "What duration would you like to change it to?"
                }
            else:
                # General modification - regenerate with updated info
                # Store the user's message as modification notes
                data['modification_notes'] = user_message
                
                # Extract any new information from their message
                if extracted:
                    for key in ['grade_level', 'subject', 'topic', 'duration', 'objectives', 
                               'class_size', 'learning_style', 'special_needs', 'resources']:
                        if extracted.get(key) and extracted[key] != 'null' and extracted[key].strip():
                            data[key] = extracted[key].strip()
                
                # Regenerate plan with updated data
                if data.get('plan_type') == 'unit':
                    lesson_plan = generate_unit_plan_with_ai(data)
                    update_msg = "Perfect! I've updated your unit plan with those changes. Here's the revised version!\n\nLet me know if you need any other changes."
                else:
                    lesson_plan = generate_lesson_plan_with_ai(data)
                    update_msg = "Perfect! I've updated your lesson plan with those changes. Here's the revised version!\n\nLet me know if you need any other changes. If not, is there anything else you'd like help with, or would you like to create another lesson plan?"
                # Clear modification notes after generation so they don't persist forever
                data.pop('modification_notes', None)
                
                return {
                    'success': True,
                    'state': state,
                    'message': update_msg,
                    'lessonPlan': lesson_plan,
                    'options': build_optional_additions(data)
                }
        else:
            # User is satisfied or said no - but check if they're asking about the lesson plan
            user_lower = user_message.lower()
            if any(phrase in user_lower for phrase in KEYWORDS_CANT_SEE_PLAN):
                # User might be asking about the lesson plan - regenerate it to be sure they see it
                lesson_plan = generate_lesson_plan_with_ai(data)
                return {
                    'success': True,
                    'state': state,
                    'message': "Here's your lesson plan!",
                    'lessonPlan': lesson_plan,
                    'options': build_optional_additions(data)
                }
            
            # CHECK FOR SATISFACTION (New Logic)
            # If user indicates they are happy, generate worksheet
            if any(phrase in user_lower for phrase in KEYWORDS_SATISFACTION):
                # Generate the worksheet/summary
                worksheet_content = generate_worksheet(data)
                
                return {
                    'success': True,
                    'state': state,
                    'message': f"I'm glad you're happy with the lesson plan! Here is a <strong>Teacher's Summary</strong> and a <strong>Student Worksheet</strong> you can use:\n\n{worksheet_content}\n\nIs there anything else I can help you with?"
                }
            
            # If not happy/changing, maybe starting new?
            state['step'] = ConversationState.GRADE_LEVEL
            state['data'] = {}
            return {
                'success': True,
                'state': state,
                'message': "Awesome! What would you like to work on next? (e.g., 'Create a new lesson plan' or 'Help me with something else')"
            }

    return {
        'success': False,
        'message': "I'm not sure what to do. Let's start over. What grade level do you teach?"
    }
