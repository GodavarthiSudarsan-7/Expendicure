# Expendicure Companion — ProGuard / R8 rules.
#
# The app has no reflection-based serialization and no third-party HTTP stack,
# so the defaults are sufficient. androidx.security's Tink dependency ships its
# own consumer rules. Keep the crash-report line numbers readable.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
