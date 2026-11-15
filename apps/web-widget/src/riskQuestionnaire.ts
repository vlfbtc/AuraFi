// Questionário de perfil de risco, o mesmo do app iOS (apps/ios/RiskQuestionnaire.swift).
// Fonte canônica: contracts/risk-questionnaire.json. O teste
// tests/unit/test_risk_questionnaire.py confere as duas versões contra ela e
// dá as mesmas respostas ao site e ao app. Mude os três arquivos juntos.
//
// O arquivo só usa sintaxe de tipos apagável, para o Node rodá-lo sem build.

export type RiskProfileLevel = 'conservative' | 'moderate' | 'aggressive';

export interface RiskOption {
  readonly id: string;
  readonly title: string;
  readonly subtitle: string;
  readonly score: number;
}

export interface RiskQuestion {
  readonly id: string;
  readonly title: string;
  readonly context: string;
  readonly options: readonly RiskOption[];
}

export const RISK_QUESTIONNAIRE_VERSION = 'aurafi-risk-2026-11';
export const CONSERVATIVE_MAX_SCORE = 3;
export const MODERATE_MAX_SCORE = 7;

export const RISK_QUESTIONS: readonly RiskQuestion[] = [
  {
    id: 'question_1',
    title: 'Se suas stablecoins caíssem 10% num mês ruim, como você reagiria?',
    context: 'Sua reação ajuda a entender quanto desconforto você aceita.',
    options: [
      { id: 'q1-a', title: 'Sairia imediatamente', subtitle: 'Não tolero perdas', score: 0 },
      { id: 'q1-b', title: 'Esperaria e entenderia', subtitle: 'Analiso antes de decidir', score: 1 },
      { id: 'q1-c', title: 'Aproveitaria para alocar mais', subtitle: 'Vejo como oportunidade', score: 2 },
    ],
  },
  {
    id: 'question_2',
    title: 'Por quanto tempo você pode manter esse valor alocado?',
    context: 'Prazos maiores podem envolver mais variação.',
    options: [
      { id: 'q2-a', title: 'Até 3 meses', subtitle: 'Posso precisar do valor logo', score: 0 },
      { id: 'q2-b', title: 'De 3 a 12 meses', subtitle: 'Tenho alguma flexibilidade', score: 1 },
      { id: 'q2-c', title: 'Mais de 12 meses', subtitle: 'Meu horizonte é longo', score: 2 },
    ],
  },
  {
    id: 'question_3',
    title: 'Quanto desse patrimônio você aceitaria expor a DeFi?',
    context: 'Diversificação reduz a dependência de uma única oportunidade.',
    options: [
      { id: 'q3-a', title: 'Até 10%', subtitle: 'Quero começar com cautela', score: 0 },
      { id: 'q3-b', title: 'Entre 10% e 30%', subtitle: 'Busco equilíbrio', score: 1 },
      { id: 'q3-c', title: 'Mais de 30%', subtitle: 'Aceito maior exposição', score: 2 },
    ],
  },
  {
    id: 'question_4',
    title: 'O que mais importa ao escolher uma oportunidade?',
    context: 'Não existe resposta certa: queremos conhecer sua prioridade.',
    options: [
      { id: 'q4-a', title: 'Segurança e liquidez', subtitle: 'Mesmo com rendimento menor', score: 0 },
      { id: 'q4-b', title: 'Equilíbrio entre risco e retorno', subtitle: 'Comparo os dois lados', score: 1 },
      { id: 'q4-c', title: 'Maior potencial de retorno', subtitle: 'Aceito mais incerteza', score: 2 },
    ],
  },
  {
    id: 'question_5',
    title: 'Como é sua experiência com protocolos DeFi?',
    context: 'A linguagem e os detalhes serão adaptados ao seu momento.',
    options: [
      { id: 'q5-a', title: 'Estou começando', subtitle: 'Preciso de explicações claras', score: 0 },
      { id: 'q5-b', title: 'Já fiz algumas alocações', subtitle: 'Conheço os conceitos principais', score: 1 },
      { id: 'q5-c', title: 'Uso DeFi com frequência', subtitle: 'Avalio protocolos e redes', score: 2 },
    ],
  },
];

export function profileForScore(score: number): RiskProfileLevel {
  if (score <= CONSERVATIVE_MAX_SCORE) return 'conservative';
  if (score <= MODERATE_MAX_SCORE) return 'moderate';
  return 'aggressive';
}

/** Perfil das respostas (id da pergunta → id da opção), ou null se faltar resposta válida. */
export function profileForAnswers(answers: Readonly<Record<string, string>>): RiskProfileLevel | null {
  let total = 0;
  for (const question of RISK_QUESTIONS) {
    const option = question.options.find((candidate) => candidate.id === answers[question.id]);
    if (!option) return null;
    total += option.score;
  }
  return profileForScore(total);
}
