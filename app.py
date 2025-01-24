import streamlit as st
from llama_index.llms.groq import Groq
import pdfplumber
import psycopg2
import os
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Groq LLM Configuration
api_key = os.getenv('GROQ_API_KEY')
llm = Groq(model="llama3-70b-8192", api_key=api_key)

# Database Connection Configuration
DB_USER = os.getenv('NEON_DB_USER')
DB_PASSWORD = os.getenv('NEON_DB_PASSWORD')
DB_HOST = os.getenv('NEON_DB_HOST')
DB_PORT = os.getenv('NEON_DB_PORT')
DB_NAME = os.getenv('NEON_DB_NAME')

def log_quiz_data(title, questions):
    try:
        # Print out connection details for debugging
        st.write(f"Connecting to database:")
        st.write(f"Host: {DB_HOST}")
        st.write(f"Port: {DB_PORT}")
        st.write(f"Database: {DB_NAME}")
        st.write(f"User: {DB_USER}")

        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cursor = conn.cursor()

        # Insert title
        cursor.execute("INSERT INTO quizzes (title) VALUES (%s) RETURNING id;", (title,))
        quiz_id = cursor.fetchone()[0]

        # Insert questions and options
        for question in questions:
            cursor.execute(
                "INSERT INTO questions (quiz_id, question, option_a, option_b, option_c, option_d) VALUES (%s, %s, %s, %s, %s, %s);",
                (quiz_id, 
                 question.get('question', ''), 
                 question['options'][0], 
                 question['options'][1], 
                 question['options'][2], 
                 question['options'][3])
            )

        conn.commit()
        st.success("Quiz data logged successfully!")
        return True
    except psycopg2.Error as e:
        # More detailed error handling
        st.error(f"PostgreSQL Error: {e}")
        # Additional context about the error
        st.error(f"Error Code: {e.pgcode}")
        st.error(f"Error Message: {e.pgerror}")
        return False
    except Exception as e:
        st.error(f"Unexpected error logging quiz data: {e}")
        return False
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def extract_text_with_pdfplumber(uploaded_file):
    text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def generate_mcq_questions(text):
    # Truncate very long text to prevent overwhelming the LLM
    max_text_length = 3000
    truncated_text = text[:max_text_length]
    
    prompt = (
        "You are an expert educational content creator. Create 5 approach-based questions "
        "based on the provided text. Each question should have:\n"
        "- A clear, concise question stem\n"
        "- 4 plausible approaches (A, B, C, D)\n"
        "- NO correct or wrong answer (all approaches are valid)\n\n"
        "Provide the output in the following EXACT JSON format, WITHOUT any additional text:\n"
        "[\n"
        "  {\n"
        "    \"question\": \"How would you approach [problem/scenario]?\",\n"
        "    \"options\": [\"Approach A\", \"Approach B\", \"Approach C\", \"Approach D\"]\n"
        "  }\n"
        "]\n\n"
        f"Text to generate questions from:\n{truncated_text}"
    )
    
    try:
        # Attempt to get the response
        response = llm.complete(prompt)
        
        # Multiple parsing attempts
        def extract_json(text):
            # Import regex
            import re
            
            # Try to find JSON-like content
            json_matches = re.findall(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
            
            if json_matches:
                for match in json_matches:
                    try:
                        # Attempt to parse each potential JSON match
                        questions = json.loads(match)
                        
                        # Validate the structure
                        if (isinstance(questions, list) and 
                            len(questions) == 5 and 
                            all('question' in q and 'options' in q for q in questions)):
                            return questions
                    except json.JSONDecodeError:
                        continue
            
            return None
        
        # First, try to extract and parse JSON
        parsed_questions = extract_json(response.text)
        
        if parsed_questions:
            return parsed_questions
        
        # Fallback: Manual parsing if automatic fails
        st.error("Automatic JSON parsing failed.")
        
        # Create a fallback set of generic questions
        questions = [
            {
                "question": f"How would you approach problem {i+1}?",
                "options": ["Approach A", "Approach B", "Approach C", "Approach D"]
            } for i in range(5)
        ]
        return questions
    
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        # Log the full error for debugging
        import traceback
        st.error(traceback.format_exc())
        return []

def main():
    st.title("PDF Approach-Based Question Generator")

    # Initialize session state for questions and title
    if 'mcq_questions' not in st.session_state:
        st.session_state.mcq_questions = None
    if 'quiz_title' not in st.session_state:
        st.session_state.quiz_title = ""

    # File upload
    uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

    if uploaded_file is not None:
        st.subheader("Extracted Text")
        with st.spinner("Extracting text..."):
            extracted_text = extract_text_with_pdfplumber(uploaded_file)
            
            # Added text verification
            st.text_area("Extracted Text Preview (First 1000 characters)", 
                         extracted_text[:1000], 
                         height=200)
            st.write(f"Total text length: {len(extracted_text)} characters")

        st.subheader("Generate Approach-Based Questions")
        if st.button("Generate Questions"):
            with st.spinner("Generating questions..."):
                mcq_questions = generate_mcq_questions(extracted_text)
                
                if mcq_questions:
                    # Store questions in session state
                    st.session_state.mcq_questions = mcq_questions
                    
                    # Display questions
                    for i, q in enumerate(mcq_questions, 1):
                        st.write(f"**Question {i}:** {q['question']}")
                        st.write("Possible Approaches:")
                        for option in q['options']:
                            st.write(f"- {option}")
                        st.markdown("---")

        # Quiz Title Input (only show if questions have been generated)
        if st.session_state.mcq_questions:
            st.subheader("Quiz Details")
            st.session_state.quiz_title = st.text_input("Enter Quiz Title", key="quiz_title_input")
            
            # Log Button
            if st.button("Log Quiz"):
                # Validate title and questions
                if st.session_state.quiz_title and st.session_state.mcq_questions:
                    # Attempt to log the quiz
                    success = log_quiz_data(
                        st.session_state.quiz_title, 
                        st.session_state.mcq_questions
                    )
                    
                    if success:
                        # Optional: Clear session state after successful logging
                        st.session_state.mcq_questions = None
                        st.session_state.quiz_title = ""
                else:
                    st.warning("Please enter a quiz title and generate questions first.")

if __name__ == "__main__":
    main()
