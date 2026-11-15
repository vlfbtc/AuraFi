import Foundation

// Questionário de perfil de risco, o mesmo do site (apps/web-widget/src/riskQuestionnaire.ts).
// Fonte canônica: contracts/risk-questionnaire.json. O teste
// tests/unit/test_risk_questionnaire.py confere as duas versões contra ela e
// dá as mesmas respostas ao site e ao app. Mude os três arquivos juntos.
//
// Só depende do Foundation e dos casos de RiskProfile, para o teste compilá-lo
// fora do Xcode.

struct RiskQuestion: Identifiable, Equatable {
    let id: String
    let title: String
    let context: String
    let options: [RiskOption]
}

struct RiskOption: Identifiable, Equatable {
    let id: String
    let title: String
    let subtitle: String
    let score: Int
}

enum RiskQuestionnaire {
    static let version = "aurafi-risk-2026-11"
    static let conservativeMaxScore = 3
    static let moderateMaxScore = 7

    static let questions: [RiskQuestion] = [
        RiskQuestion(id: "question_1", title: "Se suas stablecoins caíssem 10% num mês ruim, como você reagiria?", context: "Sua reação ajuda a entender quanto desconforto você aceita.", options: [
            RiskOption(id: "q1-a", title: "Sairia imediatamente", subtitle: "Não tolero perdas", score: 0),
            RiskOption(id: "q1-b", title: "Esperaria e entenderia", subtitle: "Analiso antes de decidir", score: 1),
            RiskOption(id: "q1-c", title: "Aproveitaria para alocar mais", subtitle: "Vejo como oportunidade", score: 2)
        ]),
        RiskQuestion(id: "question_2", title: "Por quanto tempo você pode manter esse valor alocado?", context: "Prazos maiores podem envolver mais variação.", options: [
            RiskOption(id: "q2-a", title: "Até 3 meses", subtitle: "Posso precisar do valor logo", score: 0),
            RiskOption(id: "q2-b", title: "De 3 a 12 meses", subtitle: "Tenho alguma flexibilidade", score: 1),
            RiskOption(id: "q2-c", title: "Mais de 12 meses", subtitle: "Meu horizonte é longo", score: 2)
        ]),
        RiskQuestion(id: "question_3", title: "Quanto desse patrimônio você aceitaria expor a DeFi?", context: "Diversificação reduz a dependência de uma única oportunidade.", options: [
            RiskOption(id: "q3-a", title: "Até 10%", subtitle: "Quero começar com cautela", score: 0),
            RiskOption(id: "q3-b", title: "Entre 10% e 30%", subtitle: "Busco equilíbrio", score: 1),
            RiskOption(id: "q3-c", title: "Mais de 30%", subtitle: "Aceito maior exposição", score: 2)
        ]),
        RiskQuestion(id: "question_4", title: "O que mais importa ao escolher uma oportunidade?", context: "Não existe resposta certa: queremos conhecer sua prioridade.", options: [
            RiskOption(id: "q4-a", title: "Segurança e liquidez", subtitle: "Mesmo com rendimento menor", score: 0),
            RiskOption(id: "q4-b", title: "Equilíbrio entre risco e retorno", subtitle: "Comparo os dois lados", score: 1),
            RiskOption(id: "q4-c", title: "Maior potencial de retorno", subtitle: "Aceito mais incerteza", score: 2)
        ]),
        RiskQuestion(id: "question_5", title: "Como é sua experiência com protocolos DeFi?", context: "A linguagem e os detalhes serão adaptados ao seu momento.", options: [
            RiskOption(id: "q5-a", title: "Estou começando", subtitle: "Preciso de explicações claras", score: 0),
            RiskOption(id: "q5-b", title: "Já fiz algumas alocações", subtitle: "Conheço os conceitos principais", score: 1),
            RiskOption(id: "q5-c", title: "Uso DeFi com frequência", subtitle: "Avalio protocolos e redes", score: 2)
        ])
    ]

    static func profile(forScore score: Int) -> RiskProfile {
        if score <= conservativeMaxScore { return .conservative }
        if score <= moderateMaxScore { return .moderate }
        return .aggressive
    }

    /// Perfil das respostas (id da pergunta → id da opção), ou nil se faltar resposta válida.
    static func profile(forAnswers answers: [String: String]) -> RiskProfile? {
        var total = 0
        for question in questions {
            guard let optionId = answers[question.id],
                  let option = question.options.first(where: { $0.id == optionId }) else { return nil }
            total += option.score
        }
        return profile(forScore: total)
    }
}
