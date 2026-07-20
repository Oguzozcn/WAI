/**
 * WisdomAI — QuizSessionController
 * ==================================
 * Manages the full lifecycle of an interactive quiz session:
 *  - Dynamic question fetching via /api/quiz/start
 *  - Option selection with instant feedback (accordion reveal)
 *  - Skip / Deferred queue with forced loop-back
 *  - Attempt tracking & state-locking overlay
 */

class QuizSessionController {
  /**
   * @param {Object} opts
   * @param {string} opts.userId        — current user id
   * @param {string} opts.quizId        — assigned after /api/quiz/start
   * @param {Array}  opts.questions     — question objects from API
   * @param {number} opts.attemptsRemaining
   * @param {number} opts.maxAttempts
   * @param {number} opts.passThreshold — e.g. 0.80
   */
  constructor(opts = {}) {
    this.userId = opts.userId || (window.WisdomAuth && window.WisdomAuth.getSession() || {}).user_id || 'emp_001';
    this.quizId = opts.quizId || '';
    this.quizType = opts.quizType || '';
    this.courseId = opts.courseId || '';
    this.lessonId = opts.lessonId || '';
    this.pathId = opts.pathId || '';
    this.questions = opts.questions || [];
    this.currentIndex = 0;
    this.deferredList = [];                // question IDs skipped
    this.selectedAnswers = new Map();      // questionId → selectedIndex
    this.feedbackCache = new Map();        // questionId → feedback object
    this.attemptsRemaining = opts.attemptsRemaining ?? 3;
    this.maxAttempts = opts.maxAttempts ?? 3;
    this.passThreshold = opts.passThreshold ?? 0.80;
    this.isProcessingDeferred = false;     // true when looping skipped items
    this.isLocked = false;

    // DOM references (assigned after mount)
    this._dom = {};
  }

  // Fetch the specific enrolled path this quiz belongs to (if known), else
  // fall back to the old single "latest" path — keeps links without a
  // ?path= param working exactly as before.
  _fetchPath() {
    return this.pathId
      ? fetch(`/api/learning-path/${encodeURIComponent(this.pathId)}`).then(r => r.json())
      : fetch(`/api/learning-path/latest?user_id=${this.userId}`).then(r => r.json());
  }

  _learningPathUrl() {
    return this.pathId ? `/learning-path?path=${encodeURIComponent(this.pathId)}` : '/learning-path';
  }

  // ──────────────────────────────────────────
  //  Lifecycle
  // ──────────────────────────────────────────

  /**
   * Mount the controller onto the existing quiz page DOM.
   * Expects specific data-quiz-* attributes or falls back to selectors.
   */
  mount() {
    this._dom = {
      title:            document.querySelector('[data-quiz="title"]'),
      subtitle:         document.querySelector('[data-quiz="subtitle"]'),
      questionCounter:  document.querySelector('[data-quiz="question-counter"]'),
      questionText:     document.querySelector('[data-quiz="question-text"]'),
      optionsContainer: document.querySelector('[data-quiz="options"]'),
      nextBtn:          document.querySelector('[data-quiz="next-btn"]'),
      skipBtn:          document.querySelector('[data-quiz="skip-btn"]'),
      progressCurrent:  document.querySelector('[data-quiz="progress-current"]'),
      progressTotal:    document.querySelector('[data-quiz="progress-total"]'),
      passingScore:     document.querySelector('[data-quiz="passing-score"]'),
      attemptsLeft:     document.querySelector('[data-quiz="attempts-left"]'),
      feedbackPanel:    document.querySelector('[data-quiz="feedback-panel"]'),
      lockOverlay:      document.querySelector('[data-quiz="lock-overlay"]'),
    };

    // Event bindings
    if (this._dom.nextBtn) {
      this._dom.nextBtn.addEventListener('click', () => this.next_question());
    }
    if (this._dom.skipBtn) {
      this._dom.skipBtn.addEventListener('click', () => this.skip_question());
    }

    this.update_progress_ui();
    if (this.questions.length > 0) {
      this.renderQuestion(this.currentIndex);
    }
  }

  // ──────────────────────────────────────────
  //  Core Methods
  // ──────────────────────────────────────────

  /**
   * Record a selection. Does NOT commit it — just updates the buffer.
   */
  select_option(questionId, optionIndex) {
    this.selectedAnswers.set(questionId, optionIndex);
    this._highlightSelectedOption(optionIndex);
  }

  /**
   * Skip current question: append to deferred list, advance index.
   */
  skip_question() {
    const q = this._currentQuestion();
    if (!q) return;

    // Only defer if not already answered
    if (!this.selectedAnswers.has(q.question_id) && !this.deferredList.includes(q.question_id)) {
      this.deferredList.push(q.question_id);
    }
    this._hideFeedback();
    this._advanceIndex();
  }

  /**
   * Main navigation handler:
   *  1. If an option is selected → evaluate instantly, show feedback
   *  2. After feedback is shown → advance to next question
   *  3. At end of primary list → loop back to deferred items
   *  4. All done → submit for final grading
   */
  async next_question() {
    const q = this._currentQuestion();
    if (!q) return;

    // If feedback is currently displayed, advance to next question
    if (this.feedbackCache.has(q.question_id)) {
      this._hideFeedback();
      this._advanceIndex();
      return;
    }

    // Check if an option is selected
    if (!this.selectedAnswers.has(q.question_id)) {
      this._flashMessage('Please select an answer or skip this question.');
      return;
    }

    // Evaluate the single answer for instant feedback
    const selectedIdx = this.selectedAnswers.get(q.question_id);
    this._dom.nextBtn.disabled = true;
    this._dom.nextBtn.textContent = 'Checking...';

    try {
      const feedback = await this._evaluateWithRetry(q.question_id, selectedIdx);
      this.feedbackCache.set(q.question_id, feedback);
      this.show_feedback(feedback.is_correct, feedback);

      // Update button text to indicate "Continue"
      this._dom.nextBtn.disabled = false;
      this._dom.nextBtn.innerHTML = `Continue <span class="material-symbols-outlined">arrow_forward</span>`;
    } catch (err) {
      console.error('Evaluation error:', err);
      this._dom.nextBtn.disabled = false;
      this._dom.nextBtn.innerHTML = `Next Question <span class="material-symbols-outlined">arrow_forward</span>`;
      this._flashMessage('Could not evaluate answer. Try again.');
    }
  }

  /**
   * Evaluate with automatic session recovery.
   * If the server returns 404 (quiz cache expired after restart),
   * re-fetch the quiz to re-populate the server cache and retry once.
   */
  async _evaluateWithRetry(questionId, selectedIdx) {
    try {
      return await WisdomAPI.evaluateSingleAnswer(this.quizId, questionId, selectedIdx);
    } catch (firstErr) {
      // Check if it's a 404 (expired session) — attempt recovery
      if (firstErr.message && firstErr.message.includes('expired')) {
        console.warn('Quiz session expired. Attempting recovery...');
        await this._recacheQuizOnServer();
        // Retry with the new quiz_id
        return await WisdomAPI.evaluateSingleAnswer(this.quizId, questionId, selectedIdx);
      }
      throw firstErr;
    }
  }

  /**
   * Re-send the quiz questions to the server to rebuild the cache.
   * Uses the by-lesson endpoint or start endpoint depending on URL params.
   */
  async _recacheQuizOnServer() {
    const urlParams = new URLSearchParams(window.location.search);
    const courseId = urlParams.get('course') || urlParams.get('course_id');
    const lessonId = urlParams.get('lesson') || urlParams.get('lesson_id');
    const topic = urlParams.get('topic') || '';

    let freshData;
    if (courseId && lessonId) {
      const res = await fetch(`/api/quiz/by-lesson/${courseId}/${lessonId}`);
      if (!res.ok) throw new Error('Recovery failed: could not re-fetch quiz');
      freshData = await res.json();
    } else {
      freshData = await WisdomAPI.startQuiz(topic || 'General Knowledge', this.userId);
    }

    // Update the controller's quiz ID to match the new server cache
    this.quizId = freshData.quiz_id;
    // Re-map old question IDs → new question IDs (questions are re-generated)
    // Since questions are freshly generated, update our internal list
    this.questions = freshData.questions || [];
    this._flashMessage('Session recovered. Please re-select your answer.');
    // Re-render the current question with the new data
    this.selectedAnswers.clear();
    this.feedbackCache.clear();
    this.renderQuestion(this.currentIndex);
    throw new Error('Session recovered — user must re-select.');
  }

  // ──────────────────────────────────────────
  //  Feedback UI (Accordion / Inline Reveal)
  // ──────────────────────────────────────────

  /**
   * Show the accordion feedback panel below the selected option.
   */
  show_feedback(isCorrect, feedback) {
    const panel = this._dom.feedbackPanel;
    if (!panel) return;

    // Set colour
    panel.classList.remove(
      'border-green-500', 'bg-green-50',
      'border-red-500', 'bg-red-50',
      'dark:bg-green-950', 'dark:bg-red-950',
    );

    if (isCorrect) {
      panel.classList.add('border-green-500', 'bg-green-50', 'dark:bg-green-950');
    } else {
      panel.classList.add('border-red-500', 'bg-red-50', 'dark:bg-red-950');
    }

    // Populate content
    const iconSpan = panel.querySelector('[data-feedback="icon"]');
    const titleSpan = panel.querySelector('[data-feedback="title"]');
    const whyEl = panel.querySelector('[data-feedback="why"]');
    const howEl = panel.querySelector('[data-feedback="how-to-think"]');
    const correctEl = panel.querySelector('[data-feedback="correct-answer"]');

    if (iconSpan) {
      iconSpan.textContent = isCorrect ? 'check_circle' : 'cancel';
      iconSpan.classList.toggle('text-green-600', isCorrect);
      iconSpan.classList.toggle('text-red-600', !isCorrect);
    }
    if (titleSpan) {
      titleSpan.textContent = isCorrect ? 'Correct!' : 'Incorrect';
      titleSpan.classList.toggle('text-green-700', isCorrect);
      titleSpan.classList.toggle('text-red-700', !isCorrect);
    }
    if (whyEl) {
      whyEl.textContent = feedback.feedback_why || '';
      whyEl.className = 'font-body-md text-body-md mb-2 font-medium ' + (isCorrect ? 'text-green-900' : 'text-red-900');
    }
    if (howEl) {
      howEl.textContent = feedback.feedback_how_to_think || '';
      howEl.className = 'font-body-md text-body-md ' + (isCorrect ? 'text-green-800' : 'text-red-800');
    }
    if (correctEl) {
      if (!isCorrect) {
        correctEl.textContent = `Correct answer: ${feedback.correct_answer}`;
        correctEl.style.display = '';
      } else {
        correctEl.style.display = 'none';
      }
    }

    // Also visually mark the correct option in the list
    this._markOptionsAfterFeedback(feedback);

    // Reveal panel with animation
    panel.style.maxHeight = panel.scrollHeight + 40 + 'px';
    panel.style.opacity = '1';
    panel.style.marginTop = '16px';
    panel.classList.remove('invisible');
  }

  // ──────────────────────────────────────────
  //  Progress & Attempt Tracking
  // ──────────────────────────────────────────

  update_progress_ui() {
    const { progressCurrent, progressTotal, passingScore, attemptsLeft } = this._dom;
    const answered = this.selectedAnswers.size;
    const total = this.questions.length;

    if (progressCurrent) progressCurrent.textContent = String(this.currentIndex + 1).padStart(2, '0');
    if (progressTotal)   progressTotal.textContent = `/ ${total}`;
    if (passingScore)    passingScore.textContent = Math.round(this.passThreshold * 100);
    if (attemptsLeft)    attemptsLeft.textContent = `${this.attemptsRemaining} / ${this.maxAttempts}`;
  }

  // ──────────────────────────────────────────
  //  State-Locking Engine
  // ──────────────────────────────────────────

  _checkStateLock() {
    if (this.attemptsRemaining <= 0) {
      this._activateLockOverlay();
    }
  }

  _activateLockOverlay() {
    this.isLocked = true;
    const overlay = this._dom.lockOverlay;
    if (!overlay) return;

    overlay.classList.remove('hidden');
    overlay.style.opacity = '0';
    // Trigger reflow then fade in
    requestAnimationFrame(() => {
      overlay.style.transition = 'opacity 0.4s ease';
      overlay.style.opacity = '1';
    });

    // Disable all interactive quiz elements
    if (this._dom.nextBtn)  this._dom.nextBtn.disabled = true;
    if (this._dom.skipBtn)  this._dom.skipBtn.disabled = true;
    if (this._dom.optionsContainer) {
      this._dom.optionsContainer.querySelectorAll('input').forEach(r => r.disabled = true);
    }
  }

  // ──────────────────────────────────────────
  //  Internal helpers
  // ──────────────────────────────────────────

  _currentQuestion() {
    if (this.isProcessingDeferred) {
      // In deferred mode, questions is filtered to deferred IDs
      return this.questions.find(q => q.question_id === this.deferredList[this.currentIndex]);
    }
    return this.questions[this.currentIndex] || null;
  }

  _advanceIndex() {
    if (!this.isProcessingDeferred) {
      // Normal forward navigation
      if (this.currentIndex < this.questions.length - 1) {
        this.currentIndex++;
        this.renderQuestion(this.currentIndex);
      } else {
        // Reached the end of primary list → resolve deferred queue
        this._resolveDeferredQueue();
      }
    } else {
      // Processing deferred items
      this.currentIndex++;
      if (this.currentIndex < this.deferredList.length) {
        const nextQ = this.questions.find(q => q.question_id === this.deferredList[this.currentIndex]);
        if (nextQ) {
          const realIdx = this.questions.indexOf(nextQ);
          this.renderQuestion(realIdx, true);
        }
      } else {
        // All deferred resolved → submit for final grading
        this._submitForFinalGrading();
      }
    }
  }

  _resolveDeferredQueue() {
    // Filter: only deferred items that are STILL unanswered
    this.deferredList = this.deferredList.filter(id => !this.feedbackCache.has(id));

    if (this.deferredList.length === 0) {
      // All answered → final grading
      this._submitForFinalGrading();
      return;
    }

    this.isProcessingDeferred = true;
    this.currentIndex = 0;

    const firstDeferred = this.questions.find(q => q.question_id === this.deferredList[0]);
    if (firstDeferred) {
      const realIdx = this.questions.indexOf(firstDeferred);
      this._flashMessage(`You have ${this.deferredList.length} skipped question(s) remaining.`);
      this.renderQuestion(realIdx, true);
    }
  }

  async _submitForFinalGrading() {
    // Build the answers payload
    const answers = [];
    for (const q of this.questions) {
      const sel = this.selectedAnswers.get(q.question_id);
      answers.push({
        question_id: q.question_id,
        selected_index: sel !== undefined ? sel : -1,
      });
    }

    this._dom.nextBtn.disabled = true;
    this._dom.nextBtn.textContent = 'Submitting...';
    if (this._dom.skipBtn) this._dom.skipBtn.style.display = 'none';

    try {
      const result = await WisdomAPI.evaluateQuiz(this.quizId, this.userId, answers, this.quizType, this.courseId);
      this.attemptsRemaining = result.attempts_remaining ?? this.attemptsRemaining - 1;
      this.update_progress_ui();
      this._showFinalResults(result);
    } catch (err) {
      console.error('Final evaluation error:', err);
      this._dom.nextBtn.disabled = false;
      this._dom.nextBtn.innerHTML = `Retry Submission <span class="material-symbols-outlined">refresh</span>`;
      this._flashMessage('Error submitting quiz. Please try again.');
    }
  }

  _showFinalResults(result) {
    const passed = result.passed;
    const { questionCounter, questionText, optionsContainer, nextBtn } = this._dom;

    if (questionCounter) {
      questionCounter.textContent = passed ? 'Quiz Passed!' : 'Quiz Failed';
      questionCounter.classList.add(passed ? 'text-green-600' : 'text-red-600');
    }

    if (questionText) {
      let mainMsg = passed
        ? 'Great job! You have demonstrated a solid understanding of this topic.'
        : `You need ${Math.round(this.passThreshold * 100)}% to pass. Review the materials and try again.`;

      // Show remedial course notification for failed final assessments
      let remedialBanner = '';
      if (!passed && this.quizType === 'final_assessment' && result.remedial_course_generated) {
        remedialBanner = `
          <div class="mt-4 p-4 rounded-xl border-2 border-amber-400 bg-amber-50 text-amber-900 text-sm font-medium flex gap-3 items-start">
            <span class="material-symbols-outlined text-amber-600 mt-0.5">auto_fix_high</span>
            <div>
              <p class="font-bold mb-1">Personalized Remedial Course Ready!</p>
              <p>${result.remedial_message || 'A custom course has been added to your learning path based on your gap analysis.'}</p>
              <a href="/learning-path" class="inline-block mt-2 px-4 py-1.5 bg-amber-500 text-white rounded-lg font-bold text-xs hover:bg-amber-600 transition-all">View My Learning Path</a>
            </div>
          </div>`;
      }

      questionText.innerHTML = `
        You scored <strong>${Math.round(result.score * 100)}%</strong>.<br><br>${mainMsg}${remedialBanner}
      `;
    }

    if (optionsContainer) optionsContainer.innerHTML = '';
    this._hideFeedback();

    if (nextBtn) {
      if (passed) {
        // For short quizzes: navigate to the next lesson (or final assessment if last)
        // Treat as short_quiz if quizType says so OR if a lessonId was set (by-lesson flow)
        if ((this.quizType === 'short_quiz' || this.lessonId) && this.courseId) {
          nextBtn.innerHTML = `Continue <span class="material-symbols-outlined">arrow_forward</span>`;
          nextBtn.disabled = false;
          nextBtn.onclick = async () => {
            nextBtn.disabled = true;
            nextBtn.innerHTML = `Loading... <span class="material-symbols-outlined animate-spin">progress_activity</span>`;
            try {
              const path = await this._fetchPath();
              const course = (path.courses || []).find(c => c.course_id === this.courseId);
              if (course) {
                const lessons = course.lessons || [];
                const currentIdx = lessons.findIndex(l => l.lesson_id === this.lessonId);
                if (currentIdx !== -1 && currentIdx < lessons.length - 1) {
                  // Go to next lesson
                  const next = lessons[currentIdx + 1];
                  window.location.href = `/lesson?course=${this.courseId}&lesson=${next.lesson_id}`;
                } else if (course.has_final_assessment !== false) {
                  // Last lesson — go to final assessment
                  nextBtn.innerHTML = `Take Final Assessment <span class="material-symbols-outlined">workspace_premium</span>`;
                  nextBtn.disabled = false;
                  nextBtn.onclick = () => window.location.href = `/quiz?course=${this.courseId}&type=final_assessment${this.pathId ? '&path=' + encodeURIComponent(this.pathId) : ''}`;
                } else {
                  window.location.href = this._learningPathUrl();
                }
              } else {
                window.location.href = this._learningPathUrl();
              }
            } catch {
              window.location.href = this._learningPathUrl();
            }
          };
        } else {
          // Final assessment pass — check for next course
          if (this.courseId) {
            nextBtn.innerHTML = `Continue <span class="material-symbols-outlined">arrow_forward</span>`;
            nextBtn.disabled = false;
            nextBtn.onclick = async () => {
              nextBtn.disabled = true;
              nextBtn.innerHTML = `Loading... <span class="material-symbols-outlined">progress_activity</span>`;
              try {
                const path = await this._fetchPath();
                const courses = (path.courses || []).filter(c => !c.is_remedial);
                const currentIdx = courses.findIndex(c => c.course_id === this.courseId);
                if (currentIdx !== -1 && currentIdx < courses.length - 1) {
                  const nextCourse = courses[currentIdx + 1];
                  const firstLesson = (nextCourse.lessons || [])[0];
                  if (firstLesson) {
                    window.location.href = `/lesson?course=${nextCourse.course_id}&lesson=${firstLesson.lesson_id}`;
                  } else {
                    window.location.href = `/lesson?course=${nextCourse.course_id}`;
                  }
                } else {
                  // No next course — this is the last module
                  nextBtn.innerHTML = `Return to Learning Path <span class="material-symbols-outlined">route</span>`;
                  nextBtn.disabled = false;
                  nextBtn.onclick = () => window.location.href = this._learningPathUrl();
                }
              } catch {
                window.location.href = this._learningPathUrl();
              }
            };
          } else {
            nextBtn.innerHTML = `Return to Learning Path <span class="material-symbols-outlined">route</span>`;
            nextBtn.disabled = false;
            nextBtn.onclick = () => window.location.href = this._learningPathUrl();
          }
        }
      } else {
        nextBtn.innerHTML = `Review & Retry <span class="material-symbols-outlined">refresh</span>`;
        nextBtn.disabled = false;
        nextBtn.onclick = () => window.location.reload();
        this._checkStateLock();
      }
    }
  }

  // ──────────────────────────────────────────
  //  Rendering
  // ──────────────────────────────────────────

  renderQuestion(index, isDeferred = false) {
    const q = this.questions[index];
    if (!q) return;

    const { questionCounter, questionText, optionsContainer, nextBtn, skipBtn } = this._dom;
    const displayIdx = isDeferred
      ? `Skipped ${this.currentIndex + 1} of ${this.deferredList.length}`
      : `Question ${index + 1} of ${this.questions.length}`;

    if (questionCounter) questionCounter.textContent = displayIdx;
    if (questionText)    questionText.textContent = q.text;

    // Clear and rebuild options
    if (optionsContainer) {
      optionsContainer.innerHTML = '';
      q.options.forEach((optText, optIdx) => {
        const label = document.createElement('label');
        label.className = 'quiz-option flex items-center gap-4 p-5 border border-outline-variant rounded-xl cursor-pointer hover:bg-surface-container-low transition-all group';
        label.dataset.optionIndex = optIdx;
        label.innerHTML = `
          <input class="w-5 h-5 text-primary focus:ring-primary border-outline-variant" name="quiz_option" type="radio" value="${optIdx}">
          <span class="font-body-md text-body-md text-on-surface">${optText}</span>
        `;

        const radio = label.querySelector('input');
        radio.addEventListener('change', () => {
          this.select_option(q.question_id, optIdx);
        });

        optionsContainer.appendChild(label);
      });
    }

    // Restore selection if the user already picked one (e.g. revisiting deferred)
    if (this.selectedAnswers.has(q.question_id)) {
      this._highlightSelectedOption(this.selectedAnswers.get(q.question_id));
    }

    // Update button states
    if (nextBtn) {
      nextBtn.disabled = false;
      nextBtn.innerHTML = `Next Question <span class="material-symbols-outlined">arrow_forward</span>`;
    }
    if (skipBtn) {
      if (this.quizType === 'short_quiz') {
        skipBtn.style.display = 'none';
      } else {
        skipBtn.style.display = isDeferred ? 'none' : ''; // can't skip deferred items
      }
    }

    this.update_progress_ui();
  }

  _highlightSelectedOption(selectedIdx) {
    const container = this._dom.optionsContainer;
    if (!container) return;

    container.querySelectorAll('.quiz-option').forEach(label => {
      const idx = parseInt(label.dataset.optionIndex);
      const text = label.querySelector('span:last-child');
      if (idx === selectedIdx) {
        label.classList.remove('border-outline-variant');
        label.classList.add('border-primary', 'bg-primary-container/10', 'border-2');
        if (text) { text.classList.add('text-primary', 'font-bold'); text.classList.remove('text-on-surface'); }
        const radio = label.querySelector('input');
        if (radio) radio.checked = true;
      } else {
        label.classList.remove('border-primary', 'bg-primary-container/10', 'border-2');
        label.classList.add('border-outline-variant');
        if (text) { text.classList.remove('text-primary', 'font-bold'); text.classList.add('text-on-surface'); }
      }
    });
  }

  _markOptionsAfterFeedback(feedback) {
    const container = this._dom.optionsContainer;
    if (!container) return;

    container.querySelectorAll('.quiz-option').forEach(label => {
      const idx = parseInt(label.dataset.optionIndex);
      const radio = label.querySelector('input');
      if (radio) radio.disabled = true;
      label.classList.remove('cursor-pointer', 'hover:bg-surface-container-low');

      if (idx === feedback.correct_index) {
        label.classList.remove('border-outline-variant', 'border-primary', 'bg-primary-container/10');
        label.classList.add('border-green-500', 'bg-green-50', 'border-2');
        const text = label.querySelector('span:last-child');
        if (text) { text.classList.add('text-green-700', 'font-bold'); text.classList.remove('text-on-surface', 'text-primary'); }
      } else if (idx === feedback.selected_index && !feedback.is_correct) {
        label.classList.remove('border-outline-variant', 'border-primary', 'bg-primary-container/10');
        label.classList.add('border-red-500', 'bg-red-50', 'border-2');
        const text = label.querySelector('span:last-child');
        if (text) { text.classList.add('text-red-700', 'font-bold'); text.classList.remove('text-on-surface', 'text-primary'); }
      }
    });
  }

  _hideFeedback() {
    const panel = this._dom.feedbackPanel;
    if (!panel) return;
    panel.style.maxHeight = '0';
    panel.style.opacity = '0';
    panel.style.marginTop = '0';
    panel.classList.add('invisible');
  }

  _flashMessage(msg) {
    // Simple inline toast
    const existing = document.querySelector('.quiz-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'quiz-toast fixed bottom-6 left-1/2 -translate-x-1/2 bg-inverse-surface text-inverse-on-surface px-6 py-3 rounded-xl shadow-lg z-[200] font-body-md text-body-md animate-fade-in';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
  }
}

// Pull the real server-side error message out of a failed response instead
// of discarding it — "Failed to load quiz" told nobody whether the lesson
// was missing, the user lacked access, or the server errored.
async function _quizErrorDetail(res) {
  try {
    const body = await res.json();
    if (body && body.detail) return body.detail;
  } catch (_e) { /* body wasn't JSON */ }
  return `Failed to load quiz (${res.status}).`;
}

// Full, visible failure state — the old version only touched the small
// question-text element, leaving the title stuck on "Loading Quiz..." and
// the options list, counters, etc. all showing stale placeholder content.
function _showQuizLoadError(message) {
  const titleEl = document.querySelector('[data-quiz="title"]');
  if (titleEl) titleEl.textContent = 'Couldn\'t load this quiz';

  const textEl = document.querySelector('[data-quiz="question-text"]');
  if (textEl) textEl.textContent = message || 'Something went wrong loading this quiz.';

  const counterEl = document.querySelector('[data-quiz="question-counter"]');
  if (counterEl) counterEl.textContent = '';

  const optionsEl = document.querySelector('[data-quiz="options"]');
  if (optionsEl) {
    optionsEl.innerHTML = `
      <button id="quiz-retry-btn" class="self-start px-6 py-3 bg-primary text-on-primary rounded-xl font-bold squishy-button">
        Try Again
      </button>`;
    const retryBtn = document.getElementById('quiz-retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', () => window.location.reload());
  }

  const nextBtn = document.querySelector('[data-quiz="next-btn"]');
  if (nextBtn) nextBtn.style.display = 'none';
  const skipBtn = document.querySelector('[data-quiz="skip-btn"]');
  if (skipBtn) skipBtn.style.display = 'none';
}

// ──────────────────────────────────────────
//  Auto-initialization when the DOM is ready
// ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Only run on pages that have the quiz mount point
  if (!document.querySelector('[data-quiz="options"]')) return;

  const session = window.WisdomAuth.requireAuth();
  if (!session) return;

  const urlParams = new URLSearchParams(window.location.search);
  const courseId = urlParams.get('course') || urlParams.get('course_id');
  const lessonId = urlParams.get('lesson') || urlParams.get('lesson_id');
  const topic = urlParams.get('topic') || '';
  const userId = urlParams.get('user') || session.user_id;
  const pathId = urlParams.get('path') || '';

  // Determine which initialization method to use
  let quizData = null;

  try {
    if (courseId && lessonId) {
      // Lesson-scoped short quiz (existing flow via by-lesson endpoint)
      const res = await fetch(`/api/quiz/by-lesson/${courseId}/${lessonId}?user_id=${userId}`);
      if (!res.ok) throw new Error(await _quizErrorDetail(res));
      quizData = await res.json();
      // Add default attempt info if not present
      quizData.attempts_remaining = quizData.attempts_remaining ?? 3;
      quizData.max_attempts = quizData.max_attempts ?? 3;
      quizData.pass_threshold = quizData.pass_threshold ?? 0.80;
    } else if (courseId) {
      // Course-level final assessment (no specific lesson)
      const quizType = urlParams.get('type') || 'final_assessment';
      const res = await fetch(`/api/quiz/by-course/${courseId}?type=${quizType}&user_id=${userId}`);
      if (!res.ok) throw new Error(await _quizErrorDetail(res));
      quizData = await res.json();
      // Add default attempt info if not present
      quizData.attempts_remaining = quizData.attempts_remaining ?? 3;
      quizData.max_attempts = quizData.max_attempts ?? 3;
      quizData.pass_threshold = quizData.pass_threshold ?? 0.80;
    } else if (topic) {
      // Topic-based quiz via new /api/quiz/start
      const quizType = urlParams.get('type') || 'short_quiz';
      quizData = await WisdomAPI.startQuiz(topic, userId, 'medium', 5, quizType);
    } else {
      // Fallback: generate a default quiz
      quizData = await WisdomAPI.startQuiz('General Knowledge', userId);
    }
    if (!quizData || !Array.isArray(quizData.questions) || quizData.questions.length === 0) {
      throw new Error('The quiz came back with no questions.');
    }
  } catch (err) {
    console.error('Quiz initialization error:', err);
    _showQuizLoadError(err.message);
    return;
  }

  // Check if state-locked
  if (quizData.status === 'locked') {
    const overlay = document.querySelector('[data-quiz="lock-overlay"]');
    if (overlay) overlay.classList.remove('hidden');
    return;
  }

  // Rendering can fail too (e.g. a malformed question from the LLM) — without
  // this try/catch that would be a silent uncaught error, leaving the page
  // frozen on "Loading Quiz..." with no feedback at all.
  try {
    // Initialize the controller
    const quizTypeParam = urlParams.get('type');
    const controller = new QuizSessionController({
      userId,
      quizId: quizData.quiz_id,
      questions: quizData.questions || [],
      attemptsRemaining: quizData.attempts_remaining,
      maxAttempts: quizData.max_attempts,
      passThreshold: quizData.pass_threshold,
      quizType: quizTypeParam,
      courseId,
      lessonId,
      pathId,
    });

    // Set quiz title and dynamic subtitle
    const titleEl = document.querySelector('[data-quiz="title"]');
    if (titleEl) titleEl.textContent = quizData.topic || 'Knowledge Check';

    const subtitleEl = document.querySelector('[data-quiz="subtitle"]');
    if (subtitleEl) {
      subtitleEl.textContent = quizTypeParam === 'short_quiz' ? 'Short Quiz' : 'Final Assessment';
    }

    // Hide skip button for short quizzes
    if (quizTypeParam === 'short_quiz') {
      const skipBtn = document.querySelector('[data-quiz="skip-btn"]');
      if (skipBtn) skipBtn.style.display = 'none';
    }

    controller.mount();

    // Expose for debugging
    window.__quizController = controller;
  } catch (err) {
    console.error('Quiz render error:', err);
    _showQuizLoadError('This quiz\'s data looked malformed and could not be displayed.');
  }
});
