idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_i2c
        esp_timer
)

target_link_libraries(
    ${COMPONENT_LIB}
    PRIVATE m
)