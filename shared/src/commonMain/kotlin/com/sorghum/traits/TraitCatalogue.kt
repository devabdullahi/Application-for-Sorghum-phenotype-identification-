package com.sorghum.traits

/** Which board photo a trait is read from. Each photo type has its own capture and guidance. */
enum class PhotoType {
    LEAF,
    PANICLE,
    GRAIN,
}

/** How a trait is read from its photo (ADR-0004). */
enum class TraitMethod {
    /** A pure reader in `traits` measures it from the calibrated photo (colour, size). */
    MEASURED,

    /** A head of the on-device image model classifies it; absent when the model is missing. */
    LEARNED,
}

/** Unit of a continuous trait value. Lengths are mm after calibration (CLAUDE.md, Units). */
enum class MeasurementUnit {
    GRAMS,
    MILLIMETRES,
}

/**
 * One state of a descriptor, as the descriptor list codes it.
 *
 * @param code the descriptor's state code exactly as Genesys tables store it ("1", "0", "+").
 *   Codes are strings because some descriptors use symbols, such as "+" for present.
 * @param label the descriptor's English name for the state, for display.
 */
data class DescriptorState(val code: String, val label: String)

/**
 * Bin edges that turn a continuous measurement into descriptor states.
 *
 * State i covers values from `upperEdges[i - 1]` (inclusive) up to `upperEdges[i]`
 * (exclusive); the first state is open below and the last open above. So there is one edge
 * fewer than there are states.
 *
 * @param unit the unit the edges, and every value compared with them, are in.
 * @param upperEdges strictly increasing edges.
 */
data class StateBins(val unit: MeasurementUnit, val upperEdges: List<Double>) {
    init {
        require(upperEdges.isNotEmpty()) { "Bins need at least one edge" }
        require(upperEdges.zipWithNext().all { (lower, upper) -> lower < upper }) {
            "Bin edges must strictly increase, were $upperEdges"
        }
    }
}

/**
 * A visible descriptor the app reads from photos.
 *
 * @param id stable identifier used by the model metadata, the cultivar tables and the UI.
 * @param name the descriptor's English name, for display.
 * @param states the descriptor's states in the descriptor list's order. Learned heads output
 *   probabilities in the order their metadata gives, which `shared/` maps to these codes.
 * @param continuousBins set when the trait is measured as a number (seed weight); null for
 *   traits read directly as a state.
 */
data class TraitDescriptor(
    val id: String,
    val name: String,
    val photoType: PhotoType,
    val method: TraitMethod,
    val states: List<DescriptorState>,
    val continuousBins: StateBins? = null,
) {
    init {
        require(states.size >= 2) { "Trait $id needs at least two states, had ${states.size}" }
        require(states.map { it.code }.toSet().size == states.size) { "Trait $id has duplicate state codes" }
        if (continuousBins != null) {
            require(continuousBins.upperEdges.size == states.size - 1) {
                "Trait $id has ${states.size} states, so it needs ${states.size - 1} bin edges, had ${continuousBins.upperEdges.size}"
            }
        }
    }

    /** The state codes in descriptor order. */
    val stateCodes: List<String> get() = states.map { it.code }

    /** True when [code] is one of this descriptor's state codes. */
    fun hasState(code: String): Boolean = states.any { it.code == code }
}

/**
 * The visible sorghum traits the app reads (ARCHITECTURE.md section 3.2).
 *
 * State codes and labels are those of *Descriptors for sorghum [Sorghum bicolor (L.) Moench]*,
 * IBPGR and ICRISAT, Rome and Patancheru, 1993, as published in the Genesys descriptor list
 * https://www.genesys-pgr.org/descriptorlists/6291a6d8-d034-4c16-b302-59f9e92b9cdc
 * (read 2026-10-23). The cultivar tables are built from Genesys data in the same codes, so the
 * codes here must not be renumbered. "Other" states are kept because Genesys records use them.
 */
object TraitCatalogue {

    /** Leaf midrib colour, read from the corrected colour of the midrib on a leaf photo. */
    val MIDRIB_COLOUR = TraitDescriptor(
        id = "midribColour",
        name = "Midrib colour",
        photoType = PhotoType.LEAF,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("1", "White"),
            DescriptorState("2", "Dull green"),
            DescriptorState("3", "Yellow"),
            DescriptorState("4", "Brown"),
            DescriptorState("5", "Purple"),
            DescriptorState("6", "Other"),
        ),
    )

    /**
     * Plant pigmentation ("plant colour" in the descriptor list): whether injured or senescing
     * tissue turns purple/red (pigmented) or tan. Read from the colour of leaf spots.
     * ASSUMPTION — confirm: read from the leaf photo.
     */
    val PLANT_PIGMENTATION = TraitDescriptor(
        id = "plantPigmentation",
        name = "Plant pigmentation",
        photoType = PhotoType.LEAF,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("1", "Pigmented"),
            DescriptorState("2", "Tan"),
        ),
    )

    /** Glume colour, read from the corrected colour of the glumes on a panicle photo. */
    val GLUME_COLOUR = TraitDescriptor(
        id = "glumeColour",
        name = "Glume colour",
        photoType = PhotoType.PANICLE,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("1", "White"),
            DescriptorState("2", "Sienna"),
            DescriptorState("3", "Mahogany"),
            DescriptorState("4", "Red"),
            DescriptorState("5", "Purple"),
            DescriptorState("6", "Black"),
            DescriptorState("7", "Grey"),
            DescriptorState("8", "Other"),
        ),
    )

    /**
     * Panicle ("inflorescence") compactness and shape. Shape needs a learned classifier
     * (ADR-0004), so this trait is absent when the model is missing.
     */
    val PANICLE_COMPACTNESS_AND_SHAPE = TraitDescriptor(
        id = "panicleCompactnessAndShape",
        name = "Panicle compactness and shape",
        photoType = PhotoType.PANICLE,
        method = TraitMethod.LEARNED,
        states = listOf(
            DescriptorState("1", "Very lax panicle"),
            DescriptorState("2", "Very loose erect primary branches"),
            DescriptorState("3", "Very loose drooping primary branches"),
            DescriptorState("4", "Loose erect primary branches"),
            DescriptorState("5", "Loose drooping primary branches"),
            DescriptorState("6", "Semi-loose erect primary branches"),
            DescriptorState("7", "Semi-loose drooping primary branches"),
            DescriptorState("8", "Semi-compact elliptic"),
            DescriptorState("9", "Compact elliptic"),
            DescriptorState("10", "Compact oval"),
            DescriptorState("11", "Half broom corn"),
            DescriptorState("12", "Broom corn"),
            DescriptorState("13", "Other"),
        ),
    )

    /** Grain colour, read from the corrected colour of the grains on a grain photo. */
    val GRAIN_COLOUR = TraitDescriptor(
        id = "grainColour",
        name = "Grain colour",
        photoType = PhotoType.GRAIN,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("1", "White"),
            DescriptorState("2", "Yellow"),
            DescriptorState("3", "Red"),
            DescriptorState("4", "Brown"),
            DescriptorState("5", "Buff"),
            DescriptorState("6", "Other"),
        ),
    )

    /** Grain lustre: whether the grain surface is glossy. The list codes it "0" / "+". */
    val GRAIN_LUSTRE = TraitDescriptor(
        id = "grainLustre",
        name = "Grain lustre",
        photoType = PhotoType.GRAIN,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("0", "Absent"),
            DescriptorState("+", "Present"),
        ),
    )

    /**
     * 100-seed weight in grams (at 12% moisture in the descriptor list), estimated from seed
     * size on a calibrated grain photo.
     *
     * ASSUMPTION — confirm: the descriptor list records this as a number with no coded states,
     * so the app bins it into size classes using the list's usual 3/5/7 codes for low, medium
     * and high. The edges 2.0 g and 3.0 g are an initial guess around the ~2.5 g typical of
     * sorghum germplasm; `model/` should set them from the Genesys distribution.
     */
    val HUNDRED_SEED_WEIGHT = TraitDescriptor(
        id = "hundredSeedWeight",
        name = "100-seed weight",
        photoType = PhotoType.GRAIN,
        method = TraitMethod.MEASURED,
        states = listOf(
            DescriptorState("3", "Small (under 2.0 g)"),
            DescriptorState("5", "Medium (2.0 to 3.0 g)"),
            DescriptorState("7", "Large (3.0 g or more)"),
        ),
        continuousBins = StateBins(MeasurementUnit.GRAMS, listOf(2.0, 3.0)),
    )

    /** Every trait the app reads, in display order. */
    val all: List<TraitDescriptor> = listOf(
        MIDRIB_COLOUR,
        PLANT_PIGMENTATION,
        GLUME_COLOUR,
        PANICLE_COMPACTNESS_AND_SHAPE,
        GRAIN_COLOUR,
        GRAIN_LUSTRE,
        HUNDRED_SEED_WEIGHT,
    )

    /** The descriptor with [id], or null when the catalogue has no such trait. */
    fun descriptorFor(id: String): TraitDescriptor? = all.firstOrNull { it.id == id }
}
