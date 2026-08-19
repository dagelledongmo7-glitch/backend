import os
import json
import urllib.request
import urllib.parse
import re
from collections import Counter

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')


def unavailable(message="Le service IA n'est pas configuré ou ne répond pas."):
    return {'error': message, 'serviceUnavailable': True}


FRENCH_STOP_WORDS = {
    'avec', 'dans', 'pour', 'sans', 'sous', 'entre', 'cette', 'comme', 'plus', 'moins',
    'ainsi', 'leur', 'leurs', 'dont', 'elle', 'elles', 'nous', 'vous', 'tout', 'tous',
    'être', 'avoir', 'sont', 'sera', 'peut', 'doit', 'fait', 'faire', 'selon', 'après',
    'avant', 'afin', 'concours', 'document', 'candidat', 'candidats', 'article',
}


def clean_sentences(text):
    normalized = re.sub(r'\s+', ' ', str(text or '')).strip()
    return [sentence.strip(' -•\t') for sentence in re.split(r'(?<=[.!?;:])\s+', normalized)
            if 6 <= len(sentence.split()) <= 55]


def document_keywords(text):
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]{4,}", str(text or '').lower())
    counts = Counter(word for word in words if word not in FRENCH_STOP_WORDS)
    return [word for word, _ in counts.most_common(80)]


def local_quiz_from_text(document_text, document_title, question_count):
    sentences = clean_sentences(document_text)
    keywords = document_keywords(document_text)
    if not sentences or len(keywords) < 2:
        return {'error': 'Le document ne contient pas assez de texte exploitable pour produire un quiz fidèle.'}
    try:
        requested = max(1, min(20, int(question_count)))
    except (TypeError, ValueError):
        requested = 5
    questions = []
    for sentence in sentences:
        candidates = [word for word in keywords if re.search(rf'\b{re.escape(word)}\b', sentence, re.IGNORECASE)]
        if not candidates:
            continue
        answer = max(candidates, key=len)
        distractors = [word for word in keywords if word != answer and word.lower() not in sentence.lower()][:3]
        if not distractors:
            continue
        prompt = re.sub(rf'\b{re.escape(answer)}\b', '_____ ', sentence, count=1, flags=re.IGNORECASE)
        options = [answer, *distractors]
        rotation = len(questions) % len(options)
        options = options[rotation:] + options[:rotation]
        questions.append({
            'id': len(questions) + 1,
            'question': f"Complétez cet extrait du document : « {prompt.strip()} »",
            'options': [option[:1].upper() + option[1:] for option in options],
            'correctAnswer': options.index(answer),
            'explanation': f"Le terme « {answer} » apparaît dans l'extrait source : « {sentence} »",
            'subject': 'Document importé',
        })
        if len(questions) >= requested:
            break
    if not questions:
        return {'error': 'Aucune question fiable n’a pu être extraite de ce document.'}
    return {
        'title': f"Quiz — {document_title or 'document importé'}",
        'questions': questions,
        'engine': 'local-grounded',
        'notice': 'Questions produites uniquement à partir du texte importé.',
    }


def local_material_from_text(document_text, mode):
    sentences = clean_sentences(document_text)
    if not sentences:
        return {'error': 'Le document ne contient pas assez de texte exploitable.'}
    if mode == 'summary':
        selected = sentences[:min(8, len(sentences))]
        return {'summary': '\n\n'.join(f'• {sentence}' for sentence in selected), 'engine': 'local-extractive'}
    if mode == 'flashcards':
        cards = []
        for sentence in sentences[:12]:
            words = sentence.split()
            subject = ' '.join(words[:min(6, len(words))]).rstrip(',:;')
            cards.append({'question': f"Que précise le document à propos de « {subject} » ?", 'answer': sentence})
        return {'flashcards': cards, 'engine': 'local-grounded'}
    return {'error': 'Mode de génération invalide.'}

def call_gemini_api(prompt, system_instruction=None, response_schema=None):
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    
    contents = [{"parts": [{"text": prompt}]}]
    payload = {"contents": contents}
    
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    
    if response_schema:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": response_schema
        }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = json.loads(response.read().decode('utf-8'))
            candidates = res_body.get('candidates', [])
            if candidates and 'parts' in candidates[0].get('content', {}):
                text = candidates[0]['content']['parts'][0].get('text', '')
                return text
    except Exception as e:
        print(f"[Gemini API Error] {e}")
        return None
    return None


def _normalise_words(value):
    """Jetons lexicaux stables pour les évaluateurs locaux explicables."""
    import unicodedata
    plain = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii').lower()
    ignored = {
        'avec', 'dans', 'pour', 'sans', 'une', 'des', 'les', 'est', 'sont', 'que', 'qui',
        'sur', 'par', 'aux', 'cette', 'ces', 'leur', 'leurs', 'vous', 'nous', 'votre',
        'question', 'reponse', 'candidat', 'concours', 'doit', 'peut', 'faire', 'tout',
    }
    return [word for word in re.findall(r"[a-z][a-z'-]{2,}", plain) if word not in ignored]


def _coverage(answer_words, reference_words):
    answer = set(answer_words)
    reference = list(dict.fromkeys(reference_words))[:45]
    return 0 if not reference else len(answer.intersection(reference)) / len(reference)


def _strict_failure_reason(question, answer, rubric='', minimum_words=8):
    """Retourne un motif éliminatoire avant d'attribuer le moindre point."""
    text = str(answer or '').strip()
    raw_words = re.findall(r"\b[\wÀ-ÿ'-]+\b", text)
    meaningful = set(_normalise_words(text))
    if not text or len(raw_words) < minimum_words or len(meaningful) < 4:
        return 'Réponse absente ou trop courte pour démontrer une compétence.'
    normalized = ' '.join(_normalise_words(text))
    non_answers = (
        'je ne sais pas', 'aucune reponse', 'pas de reponse', 'je ne connais pas',
        'sans reponse', 'rien a dire', 'hors sujet volontaire',
    )
    if any(value in normalized for value in non_answers):
        return 'Le candidat déclare ne pas répondre au sujet.'
    reference = set(_normalise_words(f'{question} {rubric}'))
    if reference and not meaningful.intersection(reference):
        return 'Réponse hors sujet : aucun élément attendu du sujet ou du barème n’est mobilisé.'
    return ''


def _zero_written_grade(reason):
    return {
        'score': 0, 'maxScore': 20, 'strengths': [],
        'improvements': [reason, 'Reprendre le sujet, identifier les notions du barème et construire une réponse démontrée.'],
        'detailedFeedback': f'Note éliminatoire : 0/20. {reason}',
        'breakdown': {'relevance': 0, 'structure': 0, 'development': 0, 'clarity': 0},
        'engine': 'local-rubric-v2-strict', 'isOfficial': False, 'eliminatory': True,
    }


def local_open_answer_grade(question, candidate_answer, rubric=''):
    """Correction formative hors ligne, transparente et sans hasard."""
    answer = str(candidate_answer or '').strip()
    failure = _strict_failure_reason(question, answer, rubric)
    if failure:
        return _zero_written_grade(failure)
    words = _normalise_words(answer)
    raw_words = re.findall(r"\b[\wÀ-ÿ'-]+\b", answer)
    question_words = _normalise_words(question)
    rubric_words = _normalise_words(rubric)
    subject_coverage = _coverage(words, question_words)
    rubric_coverage = _coverage(words, rubric_words) if rubric_words else subject_coverage
    reference_words = list(dict.fromkeys([*question_words, *rubric_words]))
    match_count = len(set(words).intersection(reference_words))
    relevance = min(10.0, round(3.5 * subject_coverage + 6.5 * rubric_coverage, 1))

    lowered = answer.lower()
    structure_markers = ('introduction', 'premièrement', 'deuxièmement', 'cependant',
                         'en revanche', 'ainsi', 'par conséquent', 'en conclusion', 'conclusion')
    marker_count = sum(1 for marker in structure_markers if marker in lowered)
    paragraphs = len([part for part in re.split(r'\n\s*\n|\n', answer) if part.strip()])
    structure = min(3.0, round((.5 if len(raw_words) >= 35 else 0) + min(1.5, marker_count * .4) + min(1, max(0, paragraphs - 1) * .4), 1))
    development = min(4.0, round(len(raw_words) / 50, 1))

    sentences = [item for item in re.split(r'[.!?]+', answer) if item.strip()]
    average_sentence = len(raw_words) / max(1, len(sentences))
    clarity = (1.5 if sentences and 6 <= average_sentence <= 32 else 0) + (.75 if len(sentences) >= 2 else 0) + (.75 if len(set(words)) >= 8 else 0)
    clarity = min(3.0, clarity)
    score = round(min(20, relevance + structure + development + clarity), 1)
    required_matches = 1 if len(reference_words) <= 5 else 2 if len(reference_words) <= 14 else 3
    if match_count < required_matches:
        score = min(score, 4.0)
    if len(raw_words) < 20:
        score = min(score, 6.0)

    strengths, improvements = [], []
    if relevance >= 6:
        strengths.append('La réponse mobilise plusieurs notions attendues du sujet et du corrigé de référence.')
    else:
        improvements.append('Reprendre les notions précises du sujet et les relier explicitement au raisonnement.')
    if structure >= 2:
        strengths.append('Le raisonnement comporte des repères de structure lisibles.')
    else:
        improvements.append('Ajouter une introduction, des parties reliées par des transitions et une conclusion.')
    if development >= 2.5:
        strengths.append('Le développement est suffisamment étoffé pour être évalué.')
    else:
        improvements.append('Développer les arguments avec une définition, une explication et un exemple vérifiable.')
    if clarity >= 2:
        strengths.append('La formulation est globalement lisible.')
    else:
        improvements.append('Raccourcir les phrases et ponctuer davantage la réponse.')
    return {
        'score': score, 'maxScore': 20, 'strengths': strengths, 'improvements': improvements,
        'detailedFeedback': (
            f"Barème local strict : pertinence {relevance}/10, structure {structure}/3, "
            f"développement {development}/4, clarté {clarity}/3. "
            "Cette note est formative et doit être confirmée par un enseignant pour une correction officielle."
        ),
        'breakdown': {'relevance': relevance, 'structure': structure, 'development': development, 'clarity': clarity},
        'engine': 'local-rubric-v2-strict', 'isOfficial': False, 'eliminatory': False,
    }


def local_oral_evaluation(question, transcript, duration):
    """Évalue uniquement ce qu'une transcription permet réellement d'observer."""
    answer = str(transcript or '').strip()
    failure = _strict_failure_reason(question, answer, '', minimum_words=8)
    if failure:
        return {
            'clarityScore': 0, 'relevanceScore': 0, 'structureScore': 0,
            'postureScore': None, 'postureMeasured': False,
            'coachTip': 'Répondez directement à la question avec au moins deux arguments précis.',
            'juryFeedback': f'Évaluation éliminatoire de la transcription : {failure}',
            'nextQuestion': question, 'engine': 'local-transcript-v2-strict',
            'isOfficial': False, 'eliminatory': True,
        }
    words = _normalise_words(answer)
    raw_words = re.findall(r"\b[\wÀ-ÿ'-]+\b", answer)
    coverage = _coverage(words, _normalise_words(question))
    relevance = round(min(100, coverage * 85 + min(15, len(set(words)) / 3))) if answer else 0
    sentences = [part for part in re.split(r'[.!?]+', answer) if part.strip()]
    average_sentence = len(raw_words) / max(1, len(sentences))
    filler_count = len(re.findall(r'\b(euh+|heu+|ben|genre|voilà)\b', answer.lower()))
    clarity = max(0, min(100, round(min(55, len(sentences) * 8) + (25 if 6 <= average_sentence <= 30 else 0) + min(20, len(raw_words) / 3) - filler_count * 5))) if answer else 0
    markers = ('d’abord', 'ensuite', 'cependant', 'par conséquent', 'enfin', 'en conclusion')
    marker_count = sum(1 for marker in markers if marker in answer.lower())
    structure = max(0, min(100, round(min(55, len(raw_words) / 2) + marker_count * 12))) if answer else 0
    weakest = min(relevance, clarity, structure)
    tip = ('Répondez directement à la question, puis justifiez avec deux arguments.' if relevance == weakest
           else 'Annoncez un plan simple, articulez vos idées et terminez par une conclusion.' if structure == weakest
           else 'Faites des phrases plus courtes et réduisez les mots de remplissage.')
    return {
        'clarityScore': clarity, 'relevanceScore': relevance, 'structureScore': structure,
        'postureScore': None, 'postureMeasured': False, 'coachTip': tip,
        'juryFeedback': (
            f"Évaluation locale de la transcription : pertinence {relevance}/100, clarté {clarity}/100 "
            f"et structure {structure}/100. La posture et le regard ne peuvent pas être mesurés à partir du texte."
        ),
        'nextQuestion': f"Pouvez-vous donner un exemple concret pour approfondir : {question}",
        'engine': 'local-transcript-v2-strict', 'isOfficial': False, 'eliminatory': False,
    }


def local_code_grade(question, candidate_answer, rubric='', language=''):
    """Évaluation statique : vérifie la syntaxe et les éléments du barème sans exécuter le code candidat."""
    code = str(candidate_answer or '')
    failure = _strict_failure_reason(question, code, rubric, minimum_words=3)
    if failure:
        return {
            'score': 0, 'maxScore': 20, 'strengths': [],
            'improvements': [failure, 'Écrire une solution qui respecte les entrées, le traitement et le résultat demandés.'],
            'detailedFeedback': f'Note éliminatoire : 0/20. {failure}',
            'breakdown': {'syntax': 0, 'relevance': 0, 'design': 0, 'readability': 0},
            'syntaxValid': False, 'engine': 'local-code-rubric-v2-strict',
            'isOfficial': False, 'eliminatory': True,
        }
    selected_language = str(language or 'python').lower()
    syntax_valid = True
    syntax_feedback = ''
    if selected_language == 'python':
        try:
            import ast
            ast.parse(code)
        except SyntaxError as exc:
            syntax_valid = False
            syntax_feedback = f'Erreur de syntaxe ligne {exc.lineno}: {exc.msg}.'
    elif selected_language in {'javascript', 'typescript', 'java', 'c', 'cpp', 'c++'}:
        pairs = {'(': ')', '[': ']', '{': '}'}
        stack = []
        for char in code:
            if char in pairs:
                stack.append(pairs[char])
            elif char in pairs.values() and (not stack or stack.pop() != char):
                syntax_valid = False
                break
        syntax_valid = syntax_valid and not stack
        if not syntax_valid:
            syntax_feedback = 'Les délimiteurs du code ne sont pas équilibrés.'

    code_words = _normalise_words(code)
    rubric_words = _normalise_words(rubric)
    question_words = _normalise_words(question)
    coverage = _coverage(code_words, rubric_words or question_words)
    non_empty_lines = [line for line in code.splitlines() if line.strip()]
    has_structure = any(token in code for token in ('def ', 'function ', 'class ', '=>', 'return '))
    has_control = any(token in code for token in ('if ', 'for ', 'while ', 'try', 'switch'))
    syntax_score = 5 if syntax_valid else 0
    relevance_score = min(7, round(coverage * 7, 1))
    design_score = min(5, round((2 if has_structure else 0) + (1.5 if has_control else 0) + min(1.5, len(non_empty_lines) / 15), 1))
    readability_score = min(3, round((1 if len(non_empty_lines) >= 3 else 0) + (1 if any('#' in line or '//' in line for line in non_empty_lines) else 0) + (1 if len(code) >= 60 else 0), 1))
    score = round(min(20, syntax_score + relevance_score + design_score + readability_score), 1)
    strengths = []
    improvements = []
    if syntax_valid:
        strengths.append(f'La syntaxe {selected_language} est structurellement valide.')
    else:
        improvements.append(syntax_feedback)
    if has_structure:
        strengths.append('La solution est organisée en fonction, classe ou bloc réutilisable.')
    else:
        improvements.append('Organiser la solution dans une fonction avec entrées, traitement et valeur de retour.')
    if coverage < .35:
        improvements.append('Faire apparaître plus clairement les contraintes et résultats attendus dans le barème.')
    if not any('#' in line or '//' in line for line in non_empty_lines):
        improvements.append('Ajouter un bref commentaire sur l’algorithme choisi.')
    return {
        'score': score, 'maxScore': 20, 'strengths': strengths, 'improvements': improvements,
        'detailedFeedback': (
            f'Barème local de code : syntaxe {syntax_score}/5, adéquation {relevance_score}/7, '
            f'conception {design_score}/5, lisibilité {readability_score}/3. '
            'Le code n’est pas exécuté sur le serveur ; un professeur doit confirmer sa correction fonctionnelle.'
        ),
        'breakdown': {'syntax': syntax_score, 'relevance': relevance_score, 'design': design_score, 'readability': readability_score},
        'syntaxValid': syntax_valid, 'engine': 'local-code-rubric-v2-strict', 'isOfficial': False, 'eliminatory': False,
    }


def evaluate_oral_jury(concourse, question, transcript, duration):
    strict_local = local_oral_evaluation(question, transcript, duration)
    if strict_local.get('eliminatory'):
        return strict_local
    system_instruction = (
        f"Tu es un jury d'examen oral très rigoureux et bienveillant pour le concours '{concourse or 'ENAM / Grand Concours'}'. "
        f"Analyse la réponse orale du candidat fournie en transcription, pour la question '{question}'. "
        "Une transcription hors sujet ou sans contenu démontré reçoit 0. N'évalue jamais la posture ou le regard à partir d'un texte. "
        "Fournis une évaluation précise au format JSON avec: clarityScore (0-100), relevanceScore (0-100), "
        "structureScore (0-100), coachTip (chaîne courte max 25 mots), juryFeedback (appréciation globale), nextQuestion (relance)."
    )
    prompt = f"Question: '{question}'\nTranscription candidat: '{transcript or 'Aucune réponse vocale'}'\nDurée: {duration or '01:45'} minutes."
    
    res_text = call_gemini_api(prompt, system_instruction)
    if res_text:
        try:
            # Clean markdown JSON block if present
            cleaned = res_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            result = json.loads(cleaned.strip())
            for field in ['clarityScore', 'relevanceScore', 'structureScore']:
                result[field] = max(0, min(100, float(result.get(field, 0))))
            result['postureScore'] = None
            result['postureMeasured'] = False
            result['engine'] = 'gemini-transcript-strict'
            result['isOfficial'] = False
            result['eliminatory'] = False
            return result
        except Exception:
            pass

    return strict_local

def tutor_chat_reply(tutor_name, tutor_role, history, message):
    system_instruction = (
        f"Tu es l'assistant pédagogique de {tutor_name or 'la plateforme'}, dont le rôle déclaré est {tutor_role or 'accompagnement général'}. "
        "Tu réponds sur l'ensemble des concours publiés par la plateforme, sans te limiter au concours affiché à l'écran. "
        "Réponds en français, avec professionnalisme et précision. N'invente jamais une date, une condition ou une source."
    )
    context_lines = []
    if history:
        for h in history:
            sender = 'Candidat' if h.get('sender') == 'user' else (tutor_name or 'Tuteur')
            context_lines.append(f"{sender}: {h.get('text', '')}")
    
    context_str = "\n".join(context_lines)
    prompt = f"{context_str}\nCandidat: {message}\n{tutor_name or 'Tuteur'}:"

    res_text = call_gemini_api(prompt, system_instruction)
    if res_text:
        return {"reply": res_text.strip()}

    return unavailable("Le tuteur IA est indisponible : configurez GEMINI_API_KEY puis réessayez.")

def generate_quiz_from_text(document_text, document_title, question_count=5, concourse_target=""):
    if len(str(document_text or '').strip()) < 80:
        return {'error': 'Ajoutez au moins 80 caractères de contenu avant de générer un quiz.'}
    system_instruction = (
        f"Tu es un concepteur pédagogique d'examens d'État pour les concours '{concourse_target or 'ENAM, IAI, Fonction Publique'}'. "
        "Génère un quiz QCM interactif en français à partir du texte fourni au format JSON strict: "
        "{'title': 'Titre du Quiz', 'questions': [{'id': 1, 'question': '...', 'options': ['A', 'B', 'C', 'D'], 'correctAnswer': 0, 'explanation': '...'}]}"
    )
    prompt = f"Document: '{(document_text or '')[:4000]}'\nGenerer {question_count} questions de niveau concours."

    res_text = call_gemini_api(prompt, system_instruction)
    if res_text:
        try:
            cleaned = res_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception:
            pass

    return local_quiz_from_text(document_text, document_title, question_count)


def generate_material_from_text(document_text, mode, concourse_target=""):
    if len(str(document_text or '').strip()) < 80:
        return {'error': 'Ajoutez au moins 80 caractères de contenu avant de lancer l’analyse.'}
    if mode == 'summary':
        instruction = "Produis une fiche de synthèse fidèle au document, sans ajouter de faits absents. Réponds en JSON strict: {\"summary\": \"...\"}."
    elif mode == 'flashcards':
        instruction = "Crée des flashcards uniquement à partir du document. Réponds en JSON strict: {\"flashcards\": [{\"question\": \"...\", \"answer\": \"...\"}]} ."
    else:
        return {'error': 'Mode de génération invalide.'}
    prompt = f"Concours cible: {concourse_target or 'non précisé'}\nDocument:\n{(document_text or '')[:12000]}"
    result = call_gemini_api(prompt, instruction)
    if result:
        try:
            cleaned = result.strip().removeprefix('```json').removesuffix('```').strip()
            return json.loads(cleaned)
        except Exception:
            return unavailable("Le fournisseur IA a renvoyé un format inexploitable. Aucun contenu n'a été enregistré.")
    return local_material_from_text(document_text, mode)

def orientation_advisor(diploma, interest, experience, message):
    system_instruction = (
        "Tu es un conseiller d'orientation expert des concours administratifs, militaires, technologiques et médicaux. "
        "Analyse le profil du candidat et réponds au format JSON avec 'recommendations': "
        "[{'concourse': '...', 'matchScore': 95, 'reason': '...'}] et 'advice': 'paragraphe de conseil'."
    )
    prompt = f"Profil: Diplôme={diploma}, Intérêt={interest}, Expérience={experience}, Message='{message}'"

    res_text = call_gemini_api(prompt, system_instruction)
    if res_text:
        try:
            cleaned = res_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception:
            pass

    return unavailable("Orientation indisponible : configurez GEMINI_API_KEY. Aucune recommandation fictive n'a été produite.")

def grade_open_answer(question, candidate_answer, rubric=""):
    strict_local = local_open_answer_grade(question, candidate_answer, rubric)
    if strict_local.get('eliminatory'):
        return strict_local
    system_instruction = (
        "Tu es un assistant de correction pédagogique très rigoureux, sans statut de jury officiel. "
        "Une réponse hors sujet, vide, non démontrée ou qui n'utilise aucun élément du barème reçoit 0/20. "
        "N'accorde aucun point automatique pour une simple introduction ou conclusion. Évalue au format JSON: "
        "{'score': 16, 'maxScore': 20, 'strengths': ['...'], 'improvements': ['...'], 'detailedFeedback': '...'}"
    )
    prompt = f"Question: '{question}'\nRéponse Candidat: '{candidate_answer}'\nBarème: '{rubric}'"

    res_text = call_gemini_api(prompt, system_instruction)
    if res_text:
        try:
            cleaned = res_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            result = json.loads(cleaned.strip())
            result['score'] = max(0, min(20, float(result.get('score', 0))))
            result['maxScore'] = 20
            result['engine'] = 'gemini-rubric-strict'
            result['isOfficial'] = False
            result['eliminatory'] = False
            return result
        except Exception:
            pass

    return strict_local
