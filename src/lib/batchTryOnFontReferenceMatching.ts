export interface FontReferenceMatchGarment {
  id: string
  garmentFileName: string
}

export interface FontReferenceMatchFile<T> {
  value: T
  name: string
}

export interface FontReferenceAssignment<T> {
  garmentId: string
  garmentFileName: string
  reference: FontReferenceMatchFile<T>
  matchedIdentifier: string
}

export interface FontReferenceMatchResult<T> {
  assignments: FontReferenceAssignment<T>[]
  unmatched: FontReferenceMatchFile<T>[]
  ambiguous: Array<{ reference: FontReferenceMatchFile<T>; garmentIds: string[]; identifiers: string[] }>
  duplicateGarmentMatches: Array<{ garmentId: string; references: FontReferenceMatchFile<T>[] }>
}

/** Extract stable numeric identifiers without converting them to numbers, so leading zeros survive. */
export function extractFontReferenceIdentifiers(filename: string): string[] {
  const stem = filename.replace(/\.[^.]+$/, '')
  return Array.from(new Set(stem.match(/\d{4,}/g) || []))
    .sort((left, right) => right.length - left.length || stem.lastIndexOf(right) - stem.lastIndexOf(left))
}

export function matchFontReferencesByIdentifier<T>(
  garments: FontReferenceMatchGarment[],
  references: Array<FontReferenceMatchFile<T>>,
): FontReferenceMatchResult<T> {
  const garmentIdentifiers = garments.map((garment) => ({
    garment,
    identifiers: extractFontReferenceIdentifiers(garment.garmentFileName),
  }))
  const candidates: FontReferenceAssignment<T>[] = []
  const unmatched: FontReferenceMatchFile<T>[] = []
  const ambiguous: FontReferenceMatchResult<T>['ambiguous'] = []

  for (const reference of references) {
    const identifiers = extractFontReferenceIdentifiers(reference.name)
    const matches = garmentIdentifiers.flatMap(({ garment, identifiers: garmentIds }) => {
      const common = identifiers.find((identifier) => garmentIds.includes(identifier))
      return common ? [{ garment, identifier: common }] : []
    })
    if (matches.length === 0) {
      unmatched.push(reference)
    } else if (matches.length > 1) {
      ambiguous.push({
        reference,
        garmentIds: matches.map((item) => item.garment.id),
        identifiers: matches.map((item) => item.identifier),
      })
    } else {
      candidates.push({
        garmentId: matches[0].garment.id,
        garmentFileName: matches[0].garment.garmentFileName,
        reference,
        matchedIdentifier: matches[0].identifier,
      })
    }
  }

  const byGarment = new Map<string, FontReferenceAssignment<T>[]>()
  for (const candidate of candidates) {
    byGarment.set(candidate.garmentId, [...(byGarment.get(candidate.garmentId) || []), candidate])
  }
  const duplicateGarmentMatches = Array.from(byGarment.entries())
    .filter(([, items]) => items.length > 1)
    .map(([garmentId, items]) => ({ garmentId, references: items.map((item) => item.reference) }))
  const duplicateIds = new Set(duplicateGarmentMatches.map((item) => item.garmentId))

  return {
    assignments: candidates.filter((item) => !duplicateIds.has(item.garmentId)),
    unmatched,
    ambiguous,
    duplicateGarmentMatches,
  }
}
