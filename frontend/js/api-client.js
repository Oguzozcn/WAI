/**
 * WisdomAI API Client
 * ====================
 * Lightweight fetch wrapper for all /api/* calls.
 * Every page imports this to communicate with the FastAPI backend.
 */

const WisdomAPI = (() => {
  const BASE = '';  // Same origin

  async function _request(method, path, body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${BASE}${path}`, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `API error ${res.status}`);
    }
    return res.json();
  }

  // ── User Progress ──
  async function getUserProgress(userId) {
    return _request('GET', `/api/user/${userId}/progress`);
  }

  async function updateProgress(userId, eventType, eventData) {
    return _request('POST', `/api/user/${userId}/progress`, { event_type: eventType, event_data: eventData });
  }

  // ── Learning Path ──
  async function getLearningPath(userId, role = 'new_joiner') {
    return _request('GET', `/api/user/${userId}/learning-path?role=${role}`);
  }

  async function getDailyAgenda(userId, dayNumber) {
    return _request('GET', `/api/user/${userId}/daily-agenda?day=${dayNumber}`);
  }

  // ── Quiz ──
  async function generateQuiz(topic, difficulty = 'medium', questionCount = 5, quizType = 'short_quiz') {
    return _request('POST', '/api/quiz/generate', { topic, difficulty, question_count: questionCount, quiz_type: quizType });
  }

  async function evaluateQuiz(quizId, userId, answers, quizType = 'short_quiz', courseId = '') {
    return _request('POST', '/api/quiz/evaluate', { quiz_id: quizId, user_id: userId, answers, quiz_type: quizType, course_id: courseId });
  }

  async function getReflectionPrompt(questionId, questionText, userAnswer, correctAnswer, conceptTags) {
    return _request('POST', '/api/quiz/reflection', {
      question_id: questionId, question_text: questionText,
      user_answer: userAnswer, correct_answer: correctAnswer, concept_tags: conceptTags,
    });
  }

  // ── Gap Review ──
  async function getGapReview(userId) {
    return _request('GET', `/api/user/${userId}/gap-review`);
  }

  // ── Department ──
  async function getDepartmentReadiness() {
    return _request('GET', '/api/department/readiness');
  }

  async function getAtRiskUsers() {
    return _request('GET', '/api/department/at-risk');
  }

  // ── Knowledge Base ──
  async function getKBDocuments() {
    return _request('GET', '/api/kb/documents');
  }

  async function validateDocument(content) {
    return _request('POST', '/api/kb/validate', { document_content: content });
  }

  // ── Quiz Session ──
  async function startQuiz(topic, userId = 'emp_001', difficulty = 'medium', questionCount = 5, quizType = 'short_quiz') {
    return _request('POST', '/api/quiz/start', {
      topic, user_id: userId, difficulty, question_count: questionCount, quiz_type: quizType,
    });
  }

  async function evaluateSingleAnswer(quizId, questionId, selectedIndex) {
    return _request('POST', '/api/quiz/evaluate/single', {
      quiz_id: quizId, question_id: questionId, selected_index: selectedIndex,
    });
  }

  // ── Public API ──
  return {
    getUserProgress,
    updateProgress,
    getLearningPath,
    getDailyAgenda,
    generateQuiz,
    evaluateQuiz,
    getReflectionPrompt,
    getGapReview,
    getDepartmentReadiness,
    getAtRiskUsers,
    getKBDocuments,
    validateDocument,
    startQuiz,
    evaluateSingleAnswer,
  };
})();
